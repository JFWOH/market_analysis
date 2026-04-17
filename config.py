# config.py — Configurações centralizadas do projeto market_analysis
"""
Todas as configurações do sistema devem ser definidas aqui.
Evite hardcoding em outros módulos.
"""
import os


def _env_bool(name: str, default: bool = False) -> bool:
    """Lê uma variável de ambiente como booleano."""
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    """Lê uma variável de ambiente como float."""
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# ─── Ativos ───
ASSETS = {
    'mini_indice': {
        'ticker': '^BVSP',
        'name': 'Mini Índice (Ibovespa)',
        'decimal_places': 2,
    },
    'mini_dolar': {
        'ticker': 'USDBRL=X',
        'name': 'Mini Dólar (USD/BRL)',
        'decimal_places': 4,
    },
}

# ─── Intervalos e períodos padrão ───
DEFAULT_INTERVAL = '1h'
DEFAULT_PERIOD = '1mo'
MONITORING_INTERVAL_SECONDS = 300  # 5 minutos

# ─── Backtesting ───
BACKTEST_INITIAL_CAPITAL = 100_000.0
# Custos operacionais (ajuste conforme sua corretora)
COMMISSION_PER_TRADE = _env_float("COMMISSION_PER_TRADE", 5.0)   # R$ por execução (entrada OU saída)
SLIPPAGE_PCT = _env_float("SLIPPAGE_PCT", 0.0005)                # 5 bps por execução

# ─── Dashboard ───
DASHBOARD_HOST = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", "5000"))
# NUNCA deixe debug=True em produção. Controlado por variável de ambiente.
DASHBOARD_DEBUG = _env_bool("DASHBOARD_DEBUG", default=False)

# ─── API / Segurança ───
# Se API_TOKEN estiver definido, rotas /api/* exigem "Authorization: Bearer <token>".
# Deixe vazio para desabilitar autenticação (ex: localhost apenas).
API_TOKEN: str = os.environ.get("API_TOKEN", "")
# Requisições máximas por IP por minuto nas rotas /api/* e /health.
RATE_LIMIT_PER_MINUTE: int = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "60"))

# ─── Alertas Email ───
EMAIL = {
    'from': '',          # Preencher com email remetente
    'to': '',            # Preencher com email destinatário
    'password': '',      # Preencher com senha de app (NÃO senha normal)
    'smtp_server': 'smtp.gmail.com',
    'smtp_port': 587,
}

# ─── Logging ───
LOG_LEVEL = 'INFO'
LOG_FORMAT = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'