# app.py — Dashboard web para monitoramento em tempo real
"""
Servidor Flask + Socket.IO que roda análises em background
e envia atualizações para o dashboard web.
"""
import threading
import time
import logging

from flask import Flask, render_template
from flask_socketio import SocketIO

import config
from strategy import CombinedStrategy

# ─── Setup ───

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format=config.LOG_FORMAT,
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'market_analysis_secret'
socketio = SocketIO(app, cors_allowed_origins="*")

# ─── Rotas ───

@app.route('/')
def index():
    """Página principal do dashboard."""
    return render_template('index.html')


# ─── Thread de análise ───

def analysis_thread():
    """Executa análises em loop e emite resultados via Socket.IO."""
    interval = config.MONITORING_INTERVAL_SECONDS

    while True:
        try:
            for key, asset_cfg in config.ASSETS.items():
                strategy = CombinedStrategy(
                    asset_cfg['ticker'], asset_cfg['name']
                )

                if not strategy.load_data(
                    period=config.DEFAULT_PERIOD,
                    interval=config.DEFAULT_INTERVAL
                ):
                    logger.warning("Falha ao obter dados: %s", asset_cfg['name'])
                    continue

                result = strategy.analyze()

                # Preparar dados para o frontend
                dp = asset_cfg['decimal_places']
                update = {
                    'asset_key': key,
                    'name': asset_cfg['name'],
                    'trend': result['trend'],
                    'price': f"{result['last_price']:.{dp}f}",
                    'rsi': f"{result['rsi']:.1f}" if result['rsi'] else 'N/A',
                    'atr': f"{result['atr']:.{dp}f}" if result['atr'] else 'N/A',
                    'timestamp': result['timestamp'],
                    'signals': [
                        {
                            'tipo': s['tipo'],
                            'estrategia': s['estrategia'],
                            'forca': s.get('forca', 'N/A'),
                        }
                        for s in result['signals'][-5:]
                    ],
                }

                socketio.emit('market_update', update)
                logger.info("Update enviado: %s (%s)", asset_cfg['name'], result['trend'])

        except Exception as e:
            logger.error("Erro na thread de análise: %s", e)

        time.sleep(interval)


# ─── Inicialização ───

def start_background_thread():
    """Inicia a thread de análise em background."""
    thread = threading.Thread(target=analysis_thread, daemon=True)
    thread.start()
    logger.info("Thread de análise iniciada")


if __name__ == '__main__':
    start_background_thread()
    socketio.run(
        app,
        host=config.DASHBOARD_HOST,
        port=config.DASHBOARD_PORT,
        debug=config.DASHBOARD_DEBUG,
        allow_unsafe_werkzeug=True,
    )