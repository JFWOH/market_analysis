# alerts.py — Sistema de alertas (extraído de run_analyzer.py)
import time
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

logger = logging.getLogger(__name__)


class AlertProcessor:
    """Gerencia alertas de trading, evitando duplicação.

    Extraído e melhorado a partir do run_analyzer.py original.
    """

    def __init__(self, cooldown_seconds: int = 14400):
        """
        Args:
            cooldown_seconds: Tempo mínimo entre alertas idênticos (padrão: 4h).
        """
        self.sent_alerts: dict[str, float] = {}
        self.cooldown = cooldown_seconds

    def process_signals(self, signals: list[dict], asset_name: str,
                        current_price: float, notify_fn=None) -> int:
        """Processa sinais e envia notificações (se configuradas).

        Args:
            signals: Lista de sinais de trading.
            asset_name: Nome do ativo.
            current_price: Preço atual.
            notify_fn: Função de notificação (padrão: print). Assinatura:
                       notify_fn(tipo, ativo, preco, alvo, stop, descricao).

        Returns:
            Número de alertas enviados.
        """
        count = 0
        now = time.time()

        for signal in signals:
            key = f"{asset_name}_{signal['tipo']}_{signal['estrategia']}_{signal.get('descricao', '')}"

            if key in self.sent_alerts:
                if now - self.sent_alerts[key] < self.cooldown:
                    logger.debug("Alerta ignorado (cooldown): %s", key)
                    continue

            if notify_fn:
                try:
                    notify_fn(
                        signal['tipo'], asset_name, current_price,
                        signal.get('preco_alvo', 0),
                        signal.get('stop_loss', 0),
                        signal.get('estrategia', ''),
                    )
                    count += 1
                    self.sent_alerts[key] = now
                except Exception as e:
                    logger.error("Erro ao enviar alerta: %s", e)
            else:
                # Fallback: print
                print(f"  ⚡ ALERTA {signal['tipo']}: {asset_name} @ {current_price:.4f}")
                print(f"     Estratégia: {signal['estrategia']}")
                print(f"     Alvo: {signal.get('preco_alvo', 'N/A')} | "
                      f"Stop: {signal.get('stop_loss', 'N/A')}")
                count += 1
                self.sent_alerts[key] = now

        return count


def send_email_alert(tipo: str, ativo: str, preco: float,
                     alvo: float, stop: float, descricao: str,
                     email_from: str = '', email_to: str = '',
                     password: str = '', smtp_server: str = 'smtp.gmail.com',
                     smtp_port: int = 587) -> bool:
    """Envia alerta por email quando um sinal é detectado.

    Args:
        tipo: Tipo do sinal ('Compra' ou 'Venda').
        ativo: Nome do ativo.
        preco: Preço atual.
        alvo: Preço alvo.
        stop: Stop loss.
        descricao: Descrição do sinal.
        email_from: Email remetente.
        email_to: Email destinatário.
        password: Senha de app (NÃO a senha normal).
        smtp_server: Servidor SMTP.
        smtp_port: Porta SMTP.

    Returns:
        True se enviado com sucesso.
    """
    if not email_from or not email_to or not password:
        logger.warning("Credenciais de email não configuradas. Alerta não enviado.")
        return False

    subject = f"ALERTA DE MERCADO: {tipo} {ativo}"
    body = f"""
    <html>
    <body>
    <h2>Sinal de {tipo} detectado para {ativo}</h2>
    <p><strong>Descrição:</strong> {descricao}</p>
    <p><strong>Preço atual:</strong> {preco:.4f}</p>
    <p><strong>Preço alvo:</strong> {alvo:.4f}</p>
    <p><strong>Stop loss:</strong> {stop:.4f}</p>
    <p><em>Gerado automaticamente em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</em></p>
    </body>
    </html>
    """

    msg = MIMEMultipart()
    msg['From'] = email_from
    msg['To'] = email_to
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'html'))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(email_from, password)
        server.sendmail(email_from, email_to, msg.as_string())
        server.quit()
        logger.info("Alerta enviado: %s %s", tipo, ativo)
        return True
    except Exception as e:
        logger.error("Erro ao enviar email: %s", e)
        return False
