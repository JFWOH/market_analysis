# config.py — Configurações centralizadas do projeto market_analysis
"""
Todas as configurações do sistema devem ser definidas aqui.
Evite hardcoding em outros módulos.
"""

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

# ─── Dashboard ───
DASHBOARD_HOST = '0.0.0.0'
DASHBOARD_PORT = 5000
DASHBOARD_DEBUG = True

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