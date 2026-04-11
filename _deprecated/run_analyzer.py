from market_analyzer import analisar_mercado_tempo_real
import datetime
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def enviar_alerta_email(tipo, ativo, preco, alvo, stop, descricao):
    """Envia alerta por email quando um sinal é detectado"""
    # Configuração do email - substitua com suas credenciais
    email_remetente = "jeferson_wohanka@yahoo.com.br"
    senha = "sua_senha_app"  # Importante: Use uma "senha de app" para Gmail
    email_destinatario = "jeferson_wohanka@yahoo.com.br"
    
    # Criar mensagem
    assunto = f"ALERTA DE MERCADO: {tipo} {ativo}"
    corpo = f"""
    <html>
    <body>
    <h2>Sinal de {tipo} detectado para {ativo}</h2>
    <p><strong>Descrição:</strong> {descricao}</p>
    <p><strong>Preço atual:</strong> {preco:.2f}</p>
    <p><strong>Preço alvo:</strong> {alvo:.2f}</p>
    <p><strong>Stop loss:</strong> {stop:.2f}</p>
    <p><em>Gerado automaticamente em {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</em></p>
    </body>
    </html>
    """
    
    # Configurar mensagem
    msg = MIMEMultipart()
    msg['From'] = email_remetente
    msg['To'] = email_destinatario
    msg['Subject'] = assunto
    msg.attach(MIMEText(corpo, 'html'))
    
    try:
        # Conectar ao servidor SMTP
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(email_remetente, senha)
        
        # Enviar email
        texto = msg.as_string()
        server.sendmail(email_remetente, email_destinatario, texto)
        server.quit()
        print(f"Alerta enviado por email: {tipo} {ativo}")
        return True
    except Exception as e:
        print(f"Erro ao enviar email: {e}")
        return False

class ProcessadorAlertas:
    """Gerencia alertas para evitar duplicação"""
    
    def __init__(self):
        self.alertas_enviados = {}
        
    def verificar_e_enviar(self, sinais, ativo, preco_atual):
        """Verifica sinais e envia alertas se necessário"""
        for sinal in sinais:
            # Cria uma chave única para o alerta
            chave_alerta = f"{ativo}_{sinal['tipo']}_{sinal['estrategia']}_{sinal['descricao']}"
            
            # Verifica se este alerta já foi enviado nas últimas 4 horas
            agora = time.time()
            if chave_alerta in self.alertas_enviados:
                ultimo_alerta = self.alertas_enviados[chave_alerta]
                # Se enviado há menos de 4 horas, pula
                if agora - ultimo_alerta < 14400:  # 4 horas em segundos
                    print(f"Alerta {chave_alerta} ignorado (já enviado recentemente)")
                    continue
            
            # Envia o alerta
            sucesso = enviar_alerta_email(
                sinal['tipo'], 
                ativo, 
                preco_atual,
                sinal['preco_alvo'], 
                sinal['stop_loss'], 
                sinal['descricao']
            )
            
            # Registra o alerta enviado
            if sucesso:
                self.alertas_enviados[chave_alerta] = agora

def monitoramento_continuo():
    """Executa monitoramento contínuo do mercado com alertas"""
    print("Iniciando sistema de monitoramento contínuo do mercado brasileiro")
    print("Pressione Ctrl+C para interromper")
    print("-" * 60)
    
    # Configurações de monitoramento
    intervalo_dados = '1h'      # Intervalo dos candles (1h, 4h, 1d, etc)
    periodo_analise = '1mo'     # Período de dados históricos (1mo, 3mo, 6mo)
    intervalo_checagem = 1800   # Intervalo entre verificações (em segundos) - 30 minutos
    
    # Inicializar processador de alertas
    processador = ProcessadorAlertas()
    
    while True:
        try:
            hora_atual = datetime.datetime.now().strftime('%H:%M:%S')
            data_atual = datetime.datetime.now().strftime('%d/%m/%Y')
            
            print(f"\n=== VERIFICAÇÃO DE MERCADO - {data_atual} {hora_atual} ===")
            
            # Horário de mercado (9:00 às 18:00 em dias úteis)
            agora = datetime.datetime.now()
            hora = agora.hour
            dia_semana = agora.weekday()  # 0-4 são dias úteis (seg-sex)
            
            # Verificar se estamos em horário de mercado
            mercado_aberto = (0 <= dia_semana <= 4) and (9 <= hora < 18)
            if not mercado_aberto:
                print("Mercado fechado. Verificação rápida apenas.")
            
            # Função que captura resultados da análise para processamento
            resultados = {'indices': None, 'dolar': None}
            
            def capturar_resultados(analisador, tipo, ativo):
                if analisador.obter_dados():
                    if analisador.calcular_indicadores():
                        tendencia = analisador.analisar_tendencia()
                        sinais = analisador.identificar_pontos_entrada()
                        
                        resultados[tipo] = {
                            'tendencia': tendencia,
                            'preco': analisador.ultimo_preco,
                            'sinais': sinais
                        }
                        
                        # Processa alertas se houver sinais
                        if sinais:
                            processador.verificar_e_enviar(sinais, ativo, analisador.ultimo_preco)
            
            # Configurar analisadores
            from market_analyzer import AnalisadorMercado
            
            analisador_indices = AnalisadorMercado("^BVSP", intervalo_dados, periodo_analise)
            analisador_dolar = AnalisadorMercado("USDBRL=X", intervalo_dados, periodo_analise)
            
            # Analisar mercados
            print("Analisando Mini Índice (Ibovespa)...")
            capturar_resultados(analisador_indices, 'indices', 'IBOVESPA')
            
            print("Analisando Mini Dólar (USD/BRL)...")
            capturar_resultados(analisador_dolar, 'dolar', 'USD/BRL')
            
            # Exibir resumo
            print("\n=== RESUMO DA ANÁLISE ===")
            
            for nome, resultado in resultados.items():
                if resultado:
                    titulo = "MINI ÍNDICE" if nome == 'indices' else "MINI DÓLAR"
                    print(f"\n{titulo}:")
                    print(f"Tendência: {resultado['tendencia']}")
                    print(f"Último preço: {resultado['preco']:.4f}")
                    
                    if resultado['sinais']:
                        print("Sinais de operação encontrados:")
                        for sinal in resultado['sinais']:
                            print(f"- {sinal['tipo']} ({sinal['estrategia']}): {sinal['descricao']}")
                    else:
                        print("Nenhum sinal de operação no momento.")
            
            # Definir próximo intervalo de verificação
            # Durante o horário comercial, verifica com mais frequência
            if mercado_aberto:
                tempo_espera = intervalo_checagem
            else:
                # Fora do horário comercial, verifica com menos frequência
                tempo_espera = intervalo_checagem * 2
            
            proxima_verificacao = datetime.datetime.now() + datetime.timedelta(seconds=tempo_espera)
            print(f"\nPróxima verificação: {proxima_verificacao.strftime('%H:%M:%S')}")
            
            # Aguardar até a próxima verificação
            time.sleep(tempo_espera)
            
        except KeyboardInterrupt:
            print("\nMonitoramento interrompido pelo usuário.")
            break
        except Exception as e:
            print(f"\nErro inesperado: {e}")
            import traceback
            traceback.print_exc()
            # Aguarda 5 minutos antes de tentar novamente em caso de erro
            print("Tentando novamente em 5 minutos...")
            time.sleep(300)

if __name__ == "__main__":
    print("Sistema de Análise de Mercado Brasileiro")
    print("----------------------------------------")
    print("1. Análise única")
    print("2. Monitoramento contínuo com alertas")
    
    try:
        opcao = input("Selecione uma opção (1-2): ")
        
        if opcao == "1":
            print("\nExecutando análise única...")
            analisar_mercado_tempo_real(
                mini_indices=True,
                mini_dolar=True,
                intervalo='1h',
                periodo='1mo',
                loop=False
            )
            print("Análise concluída.")
            
        elif opcao == "2":
            print("\nIniciando monitoramento contínuo...")
            monitoramento_continuo()
            
        else:
            print("Opção inválida. Executando análise única padrão.")
            analisar_mercado_tempo_real(intervalo='1h', periodo='1mo', loop=False)
            
    except Exception as e:
        print(f"ERRO: {e}")
        import traceback
        traceback.print_exc()