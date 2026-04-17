"""
tests/unit/test_app.py — Testes do dashboard Flask sem servidor em execução.

Usa app.test_client() para testar rotas HTTP e as classes de infraestrutura
(rate limiter, auth). NÃO faz chamadas de rede nem inicia threads de análise.

Executável diretamente:
    python tests/unit/test_app.py
"""

from __future__ import annotations

import os
import sys
import time
import traceback

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Importar app *antes* de alterar config para o módulo já estar carregado
import app as _app_module
from app import app, _limiter, _RateLimiter, _state_cache, _state_lock

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _client(token: str | None = None):
    """Retorna test client.

    Se *token* for fornecido (inclusive string vazia), define config.API_TOKEN.
    Se omitido (None), preserva o valor atual de config.API_TOKEN —
    útil quando o teste já definiu o token antes de chamar _client().
    """
    import config as _cfg
    if token is not None:
        _cfg.API_TOKEN = token
    app.config["TESTING"] = True
    return app.test_client()


def _reset_state():
    """Limpa estado global entre testes."""
    with _state_lock:
        _state_cache.clear()
        _app_module._signal_log.clear()
    _app_module._last_update = None
    _app_module._analysis_ok = True


# ──────────────────────────────────────────────────────────────────────────────
# /health
# ──────────────────────────────────────────────────────────────────────────────

def test_health_returns_200():
    """GET /health deve retornar 200."""
    import config as _cfg
    _cfg.API_TOKEN = ""
    _reset_state()
    c = _client()
    r = c.get("/health")
    assert r.status_code == 200, f"Esperado 200, obteve {r.status_code}"
    print("  [OK] test_health_returns_200")


def test_health_json_fields():
    """/health deve ter os campos obrigatórios."""
    import config as _cfg
    _cfg.API_TOKEN = ""
    _reset_state()
    c = _client()
    r = c.get("/health")
    data = r.get_json()
    assert data is not None, "/health deve retornar JSON"
    for field in ["status", "uptime_seconds", "last_update", "analysis_ok", "assets_cached"]:
        assert field in data, f"Campo '{field}' ausente em /health"
    print("  [OK] test_health_json_fields")


def test_health_status_ok_when_no_error():
    """/health retorna status='ok' quando _analysis_ok=True."""
    import config as _cfg
    _cfg.API_TOKEN = ""
    _reset_state()
    _app_module._analysis_ok = True
    c = _client()
    r = c.get("/health")
    assert r.get_json()["status"] == "ok"
    print("  [OK] test_health_status_ok_when_no_error")


def test_health_status_degraded_when_error():
    """/health retorna status='degraded' quando _analysis_ok=False."""
    import config as _cfg
    _cfg.API_TOKEN = ""
    _reset_state()
    _app_module._analysis_ok = False
    c = _client()
    r = c.get("/health")
    data = r.get_json()
    assert data["status"] == "degraded", f"Esperado 'degraded', obteve '{data['status']}'"
    _app_module._analysis_ok = True   # restaurar
    print("  [OK] test_health_status_degraded_when_error")


def test_health_assets_cached_count():
    """/health.assets_cached reflete o número de ativos em cache."""
    import config as _cfg
    _cfg.API_TOKEN = ""
    _reset_state()
    with _state_lock:
        _state_cache["mini_indice"] = {"trend": "Alta"}
        _state_cache["mini_dolar"]  = {"trend": "Baixa"}
    c = _client()
    r = c.get("/health")
    assert r.get_json()["assets_cached"] == 2
    _reset_state()
    print("  [OK] test_health_assets_cached_count")


# ──────────────────────────────────────────────────────────────────────────────
# /api/status
# ──────────────────────────────────────────────────────────────────────────────

def test_api_status_no_auth_when_token_empty():
    """/api/status acessível sem token quando API_TOKEN está vazio."""
    import config as _cfg
    _cfg.API_TOKEN = ""
    _reset_state()
    c = _client()
    r = c.get("/api/status")
    assert r.status_code == 200, f"Esperado 200, obteve {r.status_code}"
    print("  [OK] test_api_status_no_auth_when_token_empty")


def test_api_status_returns_401_without_token():
    """/api/status retorna 401 quando API_TOKEN está definido mas sem header."""
    import config as _cfg
    _cfg.API_TOKEN = "secret123"
    _reset_state()
    c = _client()
    r = c.get("/api/status")
    assert r.status_code == 401, f"Esperado 401, obteve {r.status_code}"
    _cfg.API_TOKEN = ""
    print("  [OK] test_api_status_returns_401_without_token")


def test_api_status_returns_403_with_wrong_token():
    """/api/status retorna 403 com token errado."""
    import config as _cfg
    _cfg.API_TOKEN = "correct_token"
    _reset_state()
    c = _client()
    r = c.get("/api/status", headers={"Authorization": "Bearer wrong_token"})
    assert r.status_code == 403, f"Esperado 403, obteve {r.status_code}"
    _cfg.API_TOKEN = ""
    print("  [OK] test_api_status_returns_403_with_wrong_token")


def test_api_status_returns_200_with_correct_token():
    """/api/status retorna 200 com token correto."""
    import config as _cfg
    _cfg.API_TOKEN = "correct_token"
    _reset_state()
    c = _client()
    r = c.get("/api/status", headers={"Authorization": "Bearer correct_token"})
    assert r.status_code == 200, f"Esperado 200, obteve {r.status_code}"
    _cfg.API_TOKEN = ""
    print("  [OK] test_api_status_returns_200_with_correct_token")


def test_api_status_returns_cached_data():
    """/api/status deve conter dados do _state_cache."""
    import config as _cfg
    _cfg.API_TOKEN = ""
    _reset_state()
    with _state_lock:
        _state_cache["mini_indice"] = {"trend": "Alta", "price": "123456.00"}
    c = _client()
    r = c.get("/api/status")
    data = r.get_json()
    assert "assets" in data
    assert "mini_indice" in data["assets"]
    assert data["assets"]["mini_indice"]["trend"] == "Alta"
    _reset_state()
    print("  [OK] test_api_status_returns_cached_data")


# ──────────────────────────────────────────────────────────────────────────────
# /api/signals
# ──────────────────────────────────────────────────────────────────────────────

def test_api_signals_returns_list():
    """/api/signals deve retornar lista (pode ser vazia)."""
    import config as _cfg
    _cfg.API_TOKEN = ""
    _reset_state()
    c = _client()
    r = c.get("/api/signals")
    assert r.status_code == 200
    data = r.get_json()
    assert "signals" in data
    assert isinstance(data["signals"], list)
    print("  [OK] test_api_signals_returns_list")


def test_api_signals_filter_by_asset():
    """/api/signals filtra por asset_key corretamente."""
    import config as _cfg
    _cfg.API_TOKEN = ""
    _reset_state()
    with _state_lock:
        _app_module._signal_log.extend([
            {"asset_key": "mini_indice", "tipo": "Compra"},
            {"asset_key": "mini_dolar",  "tipo": "Venda"},
            {"asset_key": "mini_indice", "tipo": "Venda"},
        ])
    c = _client()
    r = c.get("/api/signals?asset_key=mini_indice")
    data = r.get_json()
    assert len(data["signals"]) == 2, f"Esperado 2, obteve {len(data['signals'])}"
    assert all(s["asset_key"] == "mini_indice" for s in data["signals"])
    _reset_state()
    print("  [OK] test_api_signals_filter_by_asset")


def test_api_signals_filter_by_tipo():
    """/api/signals filtra por tipo corretamente."""
    import config as _cfg
    _cfg.API_TOKEN = ""
    _reset_state()
    with _state_lock:
        _app_module._signal_log.extend([
            {"asset_key": "mini_indice", "tipo": "Compra"},
            {"asset_key": "mini_dolar",  "tipo": "Compra"},
            {"asset_key": "mini_indice", "tipo": "Venda"},
        ])
    c = _client()
    r = c.get("/api/signals?tipo=Compra")
    data = r.get_json()
    assert len(data["signals"]) == 2
    assert all(s["tipo"] == "Compra" for s in data["signals"])
    _reset_state()
    print("  [OK] test_api_signals_filter_by_tipo")


def test_api_signals_limit_param():
    """/api/signals respeita o parâmetro limit."""
    import config as _cfg
    _cfg.API_TOKEN = ""
    _reset_state()
    with _state_lock:
        for i in range(20):
            _app_module._signal_log.append({"asset_key": "x", "tipo": "Compra"})
    c = _client()
    r = c.get("/api/signals?limit=5")
    data = r.get_json()
    assert len(data["signals"]) <= 5
    _reset_state()
    print("  [OK] test_api_signals_limit_param")


# ──────────────────────────────────────────────────────────────────────────────
# Rate limiter
# ──────────────────────────────────────────────────────────────────────────────

def test_rate_limiter_allows_within_limit():
    """Requisições dentro do limite devem ser permitidas."""
    rl = _RateLimiter(max_requests=5, window_seconds=60)
    for _ in range(5):
        assert rl.is_allowed("test_ip") is True
    print("  [OK] test_rate_limiter_allows_within_limit")


def test_rate_limiter_blocks_after_limit():
    """Requisições acima do limite devem ser bloqueadas."""
    rl = _RateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        rl.is_allowed("test_ip")
    blocked = not rl.is_allowed("test_ip")
    assert blocked, "Requisição acima do limite deveria ser bloqueada"
    print("  [OK] test_rate_limiter_blocks_after_limit")


def test_rate_limiter_isolates_keys():
    """Dois IPs diferentes não interferem um no outro."""
    rl = _RateLimiter(max_requests=2, window_seconds=60)
    rl.is_allowed("ip_a")
    rl.is_allowed("ip_a")
    assert not rl.is_allowed("ip_a")   # ip_a no limite
    assert rl.is_allowed("ip_b")       # ip_b ainda livre
    print("  [OK] test_rate_limiter_isolates_keys")


def test_rate_limiter_remaining():
    """remaining() deve retornar a contagem correta."""
    rl = _RateLimiter(max_requests=10, window_seconds=60)
    rl.is_allowed("ip")
    rl.is_allowed("ip")
    assert rl.remaining("ip") == 8
    print("  [OK] test_rate_limiter_remaining")


def test_rate_limiter_window_expires():
    """Após expiração da janela, o limite deve ser resetado."""
    rl = _RateLimiter(max_requests=2, window_seconds=1)  # janela de 1 segundo
    rl.is_allowed("ip")
    rl.is_allowed("ip")
    assert not rl.is_allowed("ip")   # bloqueado
    time.sleep(1.05)                  # janela expira
    assert rl.is_allowed("ip")       # liberado novamente
    print("  [OK] test_rate_limiter_window_expires")


def test_rate_limit_endpoint_returns_429():
    """Quando excede o limite, /health deve retornar 429."""
    import config as _cfg
    _cfg.API_TOKEN    = ""
    _cfg.RATE_LIMIT_PER_MINUTE = 2
    # Reinstanciar limiter com novo limite
    _app_module._limiter = _RateLimiter(max_requests=2, window_seconds=60)

    c = _client()
    c.get("/health")
    c.get("/health")
    r = c.get("/health")   # terceira requisição — deve ser bloqueada

    assert r.status_code == 429, f"Esperado 429, obteve {r.status_code}"

    # Restaurar limiter padrão
    _app_module._limiter = _RateLimiter(max_requests=60, window_seconds=60)
    _cfg.RATE_LIMIT_PER_MINUTE = 60
    print("  [OK] test_rate_limit_endpoint_returns_429")


# ──────────────────────────────────────────────────────────────────────────────
# AlertProcessor
# ──────────────────────────────────────────────────────────────────────────────

def test_alert_processor_cooldown():
    """AlertProcessor não deve emitir o mesmo alerta dentro do cooldown."""
    from alerts import AlertProcessor

    received: list[str] = []

    def mock_notify(tipo, ativo, preco, alvo, stop, descricao):
        received.append(f"{tipo}:{ativo}")

    ap = AlertProcessor(cooldown_seconds=3600)
    signals = [{"tipo": "Compra", "estrategia": "Pin Bar",
                "preco_alvo": 110, "stop_loss": 95}]

    count1 = ap.process_signals(signals, "Ibovespa", 100_000.0, notify_fn=mock_notify)
    count2 = ap.process_signals(signals, "Ibovespa", 100_000.0, notify_fn=mock_notify)

    assert count1 == 1, f"Esperado 1 alerta na primeira chamada, obteve {count1}"
    assert count2 == 0, f"Esperado 0 alertas (cooldown), obteve {count2}"
    print("  [OK] test_alert_processor_cooldown")


def test_alert_processor_different_signals_both_sent():
    """Sinais diferentes devem ser enviados independentemente."""
    from alerts import AlertProcessor

    received: list[str] = []

    def mock_notify(tipo, ativo, preco, alvo, stop, descricao):
        received.append(f"{tipo}:{descricao}")

    ap = AlertProcessor(cooldown_seconds=3600)
    signals = [
        {"tipo": "Compra", "estrategia": "Pin Bar", "preco_alvo": 110, "stop_loss": 95},
        {"tipo": "Venda",  "estrategia": "Engulfing", "preco_alvo": 90, "stop_loss": 105},
    ]
    count = ap.process_signals(signals, "Ibovespa", 100_000.0, notify_fn=mock_notify)
    assert count == 2, f"Esperado 2 alertas, obteve {count}"
    print("  [OK] test_alert_processor_different_signals_both_sent")


def test_alert_processor_zero_signals():
    """Lista vazia de sinais deve retornar 0."""
    from alerts import AlertProcessor
    ap = AlertProcessor()
    count = ap.process_signals([], "Ibovespa", 100_000.0)
    assert count == 0
    print("  [OK] test_alert_processor_zero_signals")


# ──────────────────────────────────────────────────────────────────────────────
# stop_event / thread control
# ──────────────────────────────────────────────────────────────────────────────

def test_stop_background_thread_sets_event():
    """stop_background_thread deve setar o stop_event."""
    _app_module._bg_stop_event = None   # reset
    thread = _app_module.start_background_thread()
    assert _app_module._bg_stop_event is not None

    _app_module.stop_background_thread()
    assert _app_module._bg_stop_event.is_set(), "stop_event deveria estar setado"
    print("  [OK] test_stop_background_thread_sets_event")


# ──────────────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────────────

_TESTS = [
    test_health_returns_200,
    test_health_json_fields,
    test_health_status_ok_when_no_error,
    test_health_status_degraded_when_error,
    test_health_assets_cached_count,
    test_api_status_no_auth_when_token_empty,
    test_api_status_returns_401_without_token,
    test_api_status_returns_403_with_wrong_token,
    test_api_status_returns_200_with_correct_token,
    test_api_status_returns_cached_data,
    test_api_signals_returns_list,
    test_api_signals_filter_by_asset,
    test_api_signals_filter_by_tipo,
    test_api_signals_limit_param,
    test_rate_limiter_allows_within_limit,
    test_rate_limiter_blocks_after_limit,
    test_rate_limiter_isolates_keys,
    test_rate_limiter_remaining,
    test_rate_limiter_window_expires,
    test_rate_limit_endpoint_returns_429,
    test_alert_processor_cooldown,
    test_alert_processor_different_signals_both_sent,
    test_alert_processor_zero_signals,
    test_stop_background_thread_sets_event,
]


def run_all() -> bool:
    passed = failed = 0
    print(f"\n{'='*60}")
    print("  Suite: app/ — rotas, rate limit, auth, alertas, estado")
    print(f"{'='*60}")
    for fn in _TESTS:
        try:
            fn()
            passed += 1
        except Exception:
            failed += 1
            print(f"  [FAIL] {fn.__name__}")
            traceback.print_exc()
    print(f"{'='*60}")
    print(f"  Resultado: {passed} passou(aram) / {failed} falhou(aram)")
    print(f"{'='*60}\n")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
