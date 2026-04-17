# app.py — Dashboard web para monitoramento em tempo real
"""
Servidor Flask + Socket.IO que roda análises em background
e envia atualizações para o dashboard web.

Segurança:
  • SECRET_KEY gerado via secrets.token_hex(32) ou variável FLASK_SECRET_KEY
  • Rotas /api/* protegidas por token Bearer opcional (API_TOKEN)
  • Rate limiter in-memory por IP (RATE_LIMIT_PER_MINUTE)
  • CORS restrito ao próprio host por padrão (DASHBOARD_CORS_ORIGINS)
  • DASHBOARD_DEBUG=false por padrão; nunca habilitar em produção
"""
from __future__ import annotations

import functools
import logging
import os
import secrets
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit

import config
from alerts import AlertProcessor
from strategy import CombinedStrategy

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format=config.LOG_FORMAT,
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Flask + Socket.IO
# ──────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.config["SECRET_KEY"] = (
    os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
)

_cors_raw     = os.environ.get("DASHBOARD_CORS_ORIGINS", "")
_cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()] or None
socketio      = SocketIO(app, cors_allowed_origins=_cors_origins)

# ──────────────────────────────────────────────────────────────────────────────
# Estado global (thread-safe via _state_lock)
# ──────────────────────────────────────────────────────────────────────────────

_state_lock:   threading.Lock = threading.Lock()
_state_cache:  dict[str, dict] = {}       # asset_key → último update emitido
_signal_log:   list[dict]      = []       # log de sinais recentes (capped)
_MAX_SIGNALS   = 200                       # máximo de sinais guardados
_server_start  = time.time()
_last_update:  float | None    = None
_analysis_ok:  bool            = True     # flag de saúde da thread de análise

# ──────────────────────────────────────────────────────────────────────────────
# Rate limiter — sliding window in-memory por IP
# ──────────────────────────────────────────────────────────────────────────────

class _RateLimiter:
    """Sliding window rate limiter (in-memory, single-process)."""

    def __init__(self, max_requests: int = 60, window_seconds: int = 60) -> None:
        self._max    = max_requests
        self._window = window_seconds
        self._hits:  dict[str, list[float]] = defaultdict(list)
        self._lock   = threading.Lock()

    def is_allowed(self, key: str) -> bool:
        """Retorna True se a requisição está dentro do limite."""
        now    = time.time()
        cutoff = now - self._window
        with self._lock:
            hits = [t for t in self._hits[key] if t > cutoff]
            if len(hits) >= self._max:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            return True

    def remaining(self, key: str) -> int:
        """Retorna requisições restantes para esta janela."""
        now    = time.time()
        cutoff = now - self._window
        with self._lock:
            hits = [t for t in self._hits[key] if t > cutoff]
            return max(0, self._max - len(hits))


_limiter = _RateLimiter(
    max_requests=config.RATE_LIMIT_PER_MINUTE,
    window_seconds=60,
)

# ──────────────────────────────────────────────────────────────────────────────
# Decorators
# ──────────────────────────────────────────────────────────────────────────────

def _rate_limited(f):
    """Aplica rate limiting por IP. Retorna 429 quando excedido."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        ip = request.remote_addr or "unknown"
        if not _limiter.is_allowed(ip):
            logger.warning("Rate limit excedido: %s → %s", ip, request.path)
            resp = jsonify({
                "error": "Too Many Requests",
                "retry_after_seconds": 60,
            })
            resp.status_code = 429
            resp.headers["Retry-After"] = "60"
            return resp
        return f(*args, **kwargs)
    return wrapper


def _require_token(f):
    """Valida Bearer token quando API_TOKEN está configurado.
    Se API_TOKEN estiver vazio, a autenticação é desabilitada.
    """
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        token = getattr(config, "API_TOKEN", "")
        if not token:
            return f(*args, **kwargs)      # auth desabilitado

        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "Unauthorized — Bearer token requerido"}), 401
        if auth[7:].strip() != token:
            return jsonify({"error": "Forbidden — token inválido"}), 403
        return f(*args, **kwargs)
    return wrapper


# ──────────────────────────────────────────────────────────────────────────────
# Rotas HTTP
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Página principal do dashboard."""
    return render_template("index.html")


@app.route("/health")
@_rate_limited
def health():
    """Endpoint de health check — não requer autenticação.

    Resposta JSON:
        status:          'ok' | 'degraded'
        uptime_seconds:  segundos desde o início do servidor
        last_update:     timestamp ISO-8601 da última análise bem-sucedida
        analysis_ok:     True se a última análise não teve erro
        assets_cached:   número de ativos com estado em cache
    """
    global _last_update, _analysis_ok

    last_iso = (
        datetime.fromtimestamp(_last_update, tz=timezone.utc).isoformat()
        if _last_update else None
    )
    status = "ok" if _analysis_ok else "degraded"

    return jsonify({
        "status":          status,
        "uptime_seconds":  round(time.time() - _server_start, 1),
        "last_update":     last_iso,
        "analysis_ok":     _analysis_ok,
        "assets_cached":   len(_state_cache),
    }), 200


@app.route("/api/status")
@_rate_limited
@_require_token
def api_status():
    """Retorna o estado atual cacheado de todos os ativos.

    Requer autenticação quando API_TOKEN estiver configurado.

    Resposta JSON:
        assets: dict[asset_key → último update]
        server_time: timestamp ISO-8601
    """
    with _state_lock:
        assets_snapshot = dict(_state_cache)

    return jsonify({
        "assets":      assets_snapshot,
        "server_time": datetime.now(tz=timezone.utc).isoformat(),
    }), 200


@app.route("/api/signals")
@_rate_limited
@_require_token
def api_signals():
    """Retorna o log de sinais recentes.

    Query params:
        asset_key: filtrar por ativo (ex: 'mini_indice')
        tipo:      filtrar por tipo ('Compra' ou 'Venda')
        limit:     máximo de registros (default: 50, max: 200)

    Requer autenticação quando API_TOKEN estiver configurado.
    """
    asset_filter = request.args.get("asset_key", "").strip()
    tipo_filter  = request.args.get("tipo", "").strip()
    try:
        limit = min(int(request.args.get("limit", 50)), _MAX_SIGNALS)
    except (ValueError, TypeError):
        limit = 50

    with _state_lock:
        signals = list(_signal_log)

    if asset_filter:
        signals = [s for s in signals if s.get("asset_key") == asset_filter]
    if tipo_filter:
        signals = [s for s in signals if s.get("tipo") == tipo_filter]

    return jsonify({
        "signals": signals[-limit:],
        "total":   len(signals),
    }), 200


# ──────────────────────────────────────────────────────────────────────────────
# Socket.IO — eventos
# ──────────────────────────────────────────────────────────────────────────────

@socketio.on("connect")
def on_connect():
    """Envia estado cacheado imediatamente ao cliente que acabou de conectar."""
    with _state_lock:
        snapshot = dict(_state_cache)

    if snapshot:
        emit("initial_state", {
            "assets":    snapshot,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        })
        logger.debug("initial_state enviado para novo cliente (%d ativos)", len(snapshot))


@socketio.on("disconnect")
def on_disconnect():
    logger.debug("Cliente Socket.IO desconectado")


# ──────────────────────────────────────────────────────────────────────────────
# Thread de análise
# ──────────────────────────────────────────────────────────────────────────────

def analysis_thread(stop_event: threading.Event | None = None) -> None:
    """Executa análises em loop e emite resultados via Socket.IO.

    Args:
        stop_event: Quando setado, o loop termina graciosamente.
                    Útil para testes e shutdown controlado.
    """
    global _last_update, _analysis_ok

    alert_processor = AlertProcessor(cooldown_seconds=14400)  # 4h de cooldown
    interval = config.MONITORING_INTERVAL_SECONDS

    while not (stop_event and stop_event.is_set()):
        try:
            for key, asset_cfg in config.ASSETS.items():
                if stop_event and stop_event.is_set():
                    break

                strategy = CombinedStrategy(asset_cfg["ticker"], asset_cfg["name"])
                if not strategy.load_data(
                    period=config.DEFAULT_PERIOD,
                    interval=config.DEFAULT_INTERVAL,
                ):
                    logger.warning("Falha ao obter dados: %s", asset_cfg["name"])
                    continue

                result = strategy.analyze()

                dp     = asset_cfg["decimal_places"]
                update = {
                    "asset_key": key,
                    "name":      asset_cfg["name"],
                    "trend":     result["trend"],
                    "price":     f"{result['last_price']:.{dp}f}",
                    "rsi":       f"{result['rsi']:.1f}" if result["rsi"] else "N/A",
                    "atr":       f"{result['atr']:.{dp}f}" if result["atr"] else "N/A",
                    "timestamp": result["timestamp"],
                    "signals": [
                        {
                            "tipo":       s["tipo"],
                            "estrategia": s["estrategia"],
                            "forca":      s.get("forca", "N/A"),
                        }
                        for s in result["signals"][-5:]
                    ],
                }

                # Atualizar cache de estado e log de sinais
                with _state_lock:
                    _state_cache[key] = update
                    for sig in result["signals"]:
                        _signal_log.append({
                            "asset_key":  key,
                            "asset_name": asset_cfg["name"],
                            "tipo":       sig["tipo"],
                            "estrategia": sig["estrategia"],
                            "preco":      result["last_price"],
                            "stop_loss":  sig.get("stop_loss"),
                            "preco_alvo": sig.get("preco_alvo"),
                            "forca":      sig.get("forca"),
                            "timestamp":  result["timestamp"],
                        })
                    # Manter log dentro do limite
                    if len(_signal_log) > _MAX_SIGNALS:
                        del _signal_log[:-_MAX_SIGNALS]

                # Processar alertas
                alert_processor.process_signals(
                    result["signals"],
                    asset_name=asset_cfg["name"],
                    current_price=result["last_price"],
                )

                # Emitir via Socket.IO
                socketio.emit("market_update", update)
                logger.info("Update emitido: %s (%s)", asset_cfg["name"], result["trend"])

            _last_update = time.time()
            _analysis_ok = True

        except Exception as exc:
            _analysis_ok = False
            logger.error("Erro na thread de análise: %s", exc, exc_info=True)

        # Aguarda antes do próximo ciclo (interrompível via stop_event)
        for _ in range(interval):
            if stop_event and stop_event.is_set():
                break
            time.sleep(1)

    logger.info("Thread de análise encerrada")


# ──────────────────────────────────────────────────────────────────────────────
# Inicialização
# ──────────────────────────────────────────────────────────────────────────────

_bg_stop_event: threading.Event | None = None


def start_background_thread() -> threading.Thread:
    """Inicia a thread de análise em background.

    Returns:
        Thread iniciada (daemon=True).
    """
    global _bg_stop_event
    _bg_stop_event = threading.Event()
    thread = threading.Thread(
        target=analysis_thread,
        args=(_bg_stop_event,),
        daemon=True,
        name="market-analysis",
    )
    thread.start()
    logger.info("Thread de análise iniciada (daemon)")
    return thread


def stop_background_thread() -> None:
    """Sinaliza a thread de análise para encerrar graciosamente."""
    if _bg_stop_event:
        _bg_stop_event.set()
        logger.info("Sinal de parada enviado à thread de análise")


if __name__ == "__main__":
    start_background_thread()
    run_kwargs: dict = {
        "host":  config.DASHBOARD_HOST,
        "port":  config.DASHBOARD_PORT,
        "debug": config.DASHBOARD_DEBUG,
    }
    if config.DASHBOARD_DEBUG:
        run_kwargs["allow_unsafe_werkzeug"] = True
        logger.warning(
            "Dashboard em modo DEBUG — NÃO use em producao. "
            "Defina DASHBOARD_DEBUG=false."
        )
    socketio.run(app, **run_kwargs)
