# Guia de Uso — Sistema de Análise de Mercado Brasileiro

> Monitoramento automático de Mini Índice (WIN) e Mini Dólar (WDO)  
> com sinais de compra/venda, backtesting e painel web em tempo real.

---

## Índice

1. [Requisitos](#1-requisitos)
2. [Instalação](#2-instalação)
3. [Configuração](#3-configuração)
4. [Como usar — linha de comando](#4-como-usar--linha-de-comando)
5. [Como usar — painel web](#5-como-usar--painel-web)
6. [Entendendo os sinais](#6-entendendo-os-sinais)
7. [Configurando alertas por email](#7-configurando-alertas-por-email)
8. [Rodando os testes](#8-rodando-os-testes)
9. [Estrutura dos arquivos](#9-estrutura-dos-arquivos)
10. [Perguntas frequentes](#10-perguntas-frequentes)

---

## 1. Requisitos

- **Python 3.11 ou superior**
- Conexão com a internet (para baixar os preços)
- Windows, Linux ou macOS

Bibliotecas necessárias:

| Biblioteca | Versão testada | Para que serve |
|---|---|---|
| flask | 3.1+ | Painel web |
| flask-socketio | 5.6+ | Atualização em tempo real |
| yfinance | 0.2+ | Baixar preços do Yahoo Finance |
| pandas | 2.2+ | Cálculos e tabelas |
| numpy | 2.2+ | Operações matemáticas |

---

## 2. Instalação

```bash
# 1. Clonar ou copiar o projeto
cd market_analysis

# 2. Criar ambiente virtual (recomendado)
python -m venv venv

# 3. Ativar o ambiente
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# 4. Instalar dependências
pip install flask flask-socketio yfinance pandas numpy
```

---

## 3. Configuração

Abra o arquivo **`config.py`** e ajuste conforme necessário:

```python
# ─── Ativos monitorados ───────────────────────────────────────────
# Por padrão: Mini Índice (^BVSP) e Mini Dólar (USDBRL=X)
# Para adicionar um ativo, copie o bloco e altere ticker/nome.
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

# ─── Frequência de atualização ────────────────────────────────────
MONITORING_INTERVAL_SECONDS = 300   # 300 = a cada 5 minutos

# ─── Dados históricos ─────────────────────────────────────────────
DEFAULT_INTERVAL = '1h'    # candles de 1 hora
DEFAULT_PERIOD   = '1mo'   # último 1 mês de dados

# ─── Backtesting ──────────────────────────────────────────────────
BACKTEST_INITIAL_CAPITAL = 100_000.0   # capital inicial em R$

# ─── Painel web ───────────────────────────────────────────────────
DASHBOARD_HOST  = '127.0.0.1'   # use '0.0.0.0' para acessar de outro computador
DASHBOARD_PORT  = 5000
DASHBOARD_DEBUG = False          # NUNCA mude para True em produção
```

### Variáveis de ambiente (opcional)

Você pode sobrescrever qualquer configuração sem editar o arquivo:

```bash
# Windows (PowerShell)
$env:DASHBOARD_PORT         = "8080"
$env:RATE_LIMIT_PER_MINUTE  = "30"
$env:API_TOKEN              = "minha-senha-secreta"

# Linux / macOS
export DASHBOARD_PORT=8080
export RATE_LIMIT_PER_MINUTE=30
export API_TOKEN="minha-senha-secreta"
```

---

## 4. Como usar — linha de comando

Execute o script principal e escolha o modo desejado:

```bash
python run.py
```

Você verá o menu:

```
============================================================
  SISTEMA DE ANÁLISE DE MERCADO BRASILEIRO
  16/04/2026 22:30:00
============================================================

  Modos de operação:
  1. Análise única
  2. Monitoramento contínuo
  3. Backtesting
  4. Otimização de parâmetros

  Selecione (1-4):
```

---

### Modo 1 — Análise única

Baixa os preços agora, calcula os indicadores e mostra os sinais encontrados.  
**Ideal para:** verificar o mercado rapidamente antes de operar.

```
  Mini Índice (Ibovespa) (^BVSP)
  ──────────────────────────────────────────────────
  Tendência:    Alta
  Último Preço: 128450.00
  RSI:          62.3
  ATR:          850.00

  Sinais encontrados: 2
    • Compra | EMA + Price Action
      Preço: 128450.00 → Alvo: 131725.00 | Stop: 127175.00
    • Compra | Bollinger Bands + Price Action
      Preço: 128450.00 → Alvo: 130950.00 | Stop: 127600.00
```

---

### Modo 2 — Monitoramento contínuo

Fica rodando em loop, atualizando a cada 5 minutos (configurável).  
Exibe alertas no terminal quando novos sinais aparecem.  
**Ideal para:** deixar rodando durante o pregão.

```bash
python run.py
# Selecione 2

# Para parar: pressione Ctrl+C
```

> **Dica:** para rodar em segundo plano no Linux/macOS:
> ```bash
> nohup python run.py <<< "2" > mercado.log 2>&1 &
> ```

---

### Modo 3 — Backtesting

Simula o desempenho da estratégia em dados históricos e mostra métricas detalhadas.  
**Ideal para:** avaliar se a estratégia funciona antes de usar dinheiro real.

Saída esperada:

```
  Backtest: Mini Índice (Ibovespa)
  ──────────────────────────────────────────────────
  Período:        01/01/2024 a 31/12/2025
  Capital inicial: R$ 100.000,00
  Capital final:   R$ 118.340,00

  Retorno total:    +18.34%
  Sharpe Ratio:      1.42
  Sortino Ratio:     1.87
  Calmar Ratio:      0.95
  Max Drawdown:     -12.8%

  Total de operações: 47
    Ganhadoras:  29 (61.7%)
    Perdedoras:  18 (38.3%)
  Expectativa:  R$ 389,00 por operação

  Gráficos salvos: backtest_mini_indice.png
```

---

### Modo 4 — Otimização de parâmetros

Testa centenas de combinações de parâmetros automaticamente e encontra a configuração  
com melhor desempenho histórico. Valida o resultado em dados que o modelo nunca viu.  
**Ideal para:** ajustar a estratégia periodicamente (ex: todo mês).

> ⚠️ Este modo pode demorar alguns minutos dependendo do computador.

---

## 5. Como usar — painel web

O painel atualiza os preços e sinais automaticamente no navegador, sem precisar recarregar a página.

### Iniciar o servidor

```bash
python app.py
```

Saída esperada:
```
Thread de análise iniciada (daemon)
* Running on http://127.0.0.1:5000
```

### Acessar no navegador

Abra: **http://127.0.0.1:5000**

Para acessar de outro computador na mesma rede, defina no `config.py`:
```python
DASHBOARD_HOST = '0.0.0.0'
```
E acesse pelo IP da máquina que está rodando o servidor: `http://192.168.x.x:5000`

---

### Rotas da API (para integração)

| Rota | Método | Autenticação | Descrição |
|---|---|---|---|
| `/` | GET | Não | Painel web |
| `/health` | GET | Não | Status do servidor |
| `/api/status` | GET | Sim* | Último estado de todos os ativos |
| `/api/signals` | GET | Sim* | Log de sinais recentes |

*Somente se `API_TOKEN` estiver configurado.

#### Exemplos de uso da API

```bash
# Verificar saúde do servidor
curl http://127.0.0.1:5000/health

# Listar estado dos ativos (sem auth)
curl http://127.0.0.1:5000/api/status

# Listar estado dos ativos (com auth)
curl -H "Authorization: Bearer minha-senha-secreta" \
     http://127.0.0.1:5000/api/status

# Filtrar sinais de compra do Mini Índice (últimos 10)
curl "http://127.0.0.1:5000/api/signals?asset_key=mini_indice&tipo=Compra&limit=10"
```

#### Resposta de `/health`

```json
{
  "status": "ok",
  "uptime_seconds": 3720.5,
  "last_update": "2026-04-16T22:30:00+00:00",
  "analysis_ok": true,
  "assets_cached": 2
}
```

> **Limite de requisições:** por padrão, máximo de **60 por minuto por IP**.  
> Se exceder, a API retorna `HTTP 429` e você deve aguardar 60 segundos.

---

## 6. Entendendo os sinais

### O que é um sinal?

Um sinal aparece quando **dois critérios se alinham ao mesmo tempo**:

1. **Indicador técnico** confirma a tendência (ex: EMA curta > EMA longa = tendência de alta)
2. **Padrão de candle** (Price Action) aparece no mesmo sentido

### Tipos de sinal

| Tipo | Significa |
|---|---|
| **Compra** | A análise sugere que o preço pode subir |
| **Venda** | A análise sugere que o preço pode cair |

### Força do sinal (1–10)

| Faixa | Interpretação |
|---|---|
| 9–10 | Sinal muito forte (ex: rompimento falso confirmado) |
| 7–8 | Sinal forte (ex: pin bar, engolfamento) |
| 5–6 | Sinal moderado (ex: padrão de dois candles) |
| ≤ 4 | Sinal fraco — use com cautela |

### Padrões detectados

| Padrão | Força | Descrição |
|---|---|---|
| Rompimento falso | 9 | Preço rompe o suporte/resistência e volta |
| Pin bar | 8 | Candle com sombra longa (rejeição de preço) |
| Engolfamento | 8 | Um candle "engole" o anterior no sentido oposto |
| Reversão de dois candles | 7 | Dois candles consecutivos invertendo direção |
| Doji | 6 | Indecisão — abertura e fechamento quase iguais |

### Estratégias combinadas

| Estratégia | Indicadores usados |
|---|---|
| EMA + Price Action | Médias de 21 e 55 períodos |
| RSI + Price Action | RSI de 14 períodos |
| MACD + Price Action | MACD (12, 26, 9) |
| Bollinger Bands + Price Action | Bandas de 20 períodos, 2 desvios |

---

## 7. Configurando alertas por email

Edite o arquivo `config.py`:

```python
EMAIL = {
    'from':        'seu_email@gmail.com',
    'to':          'destino@gmail.com',
    'password':    'xxxx xxxx xxxx xxxx',  # Senha de app do Google (não a senha normal!)
    'smtp_server': 'smtp.gmail.com',
    'smtp_port':   587,
}
```

### Como criar uma senha de app no Gmail

1. Acesse sua conta Google → **Segurança**
2. Ative a **Verificação em duas etapas** (se ainda não estiver ativa)
3. Pesquise por **"Senhas de app"**
4. Crie uma senha para o app "Market Analysis"
5. Copie os 16 caracteres gerados e cole no campo `password`

> ⚠️ **Nunca coloque sua senha normal do Gmail.** Use sempre a Senha de App.

---

## 8. Rodando os testes

Para verificar se tudo está funcionando corretamente:

```bash
# Rodar todos os testes de uma vez
python tests/unit/test_data.py
python tests/unit/test_indicators.py
python tests/unit/test_backtester.py
python tests/unit/test_strategy.py
python tests/unit/test_optimizer.py
python tests/unit/test_app.py
```

Saída esperada (todos devem mostrar `0 falhou`):
```
  Resultado: 12 passou(aram) / 0 falhou(aram)
  Resultado: 26 passou(aram) / 0 falhou(aram)
  Resultado: 21 passou(aram) / 0 falhou(aram)
  Resultado: 26 passou(aram) / 0 falhou(aram)
  Resultado: 19 passou(aram) / 0 falhou(aram)
  Resultado: 24 passou(aram) / 0 falhou(aram)
```

Se tiver `pytest` instalado:
```bash
pytest tests/ -v
```

---

## 9. Estrutura dos arquivos

```
market_analysis/
│
├── run.py              ← Ponto de entrada (menu de modos)
├── app.py              ← Painel web (Flask + Socket.IO)
├── config.py           ← Todas as configurações
│
├── strategy.py         ← Lógica principal de análise
├── indicators.py       ← Cálculo dos indicadores técnicos
├── price_action.py     ← Detecção de padrões de candle
├── backtester.py       ← Simulação histórica
├── optimizer.py        ← Otimização de parâmetros
├── alerts.py           ← Sistema de alertas e emails
│
├── data/               ← Camada de dados
│   ├── providers.py    ← Conexão com Yahoo Finance
│   ├── cache.py        ← Cache local de preços
│   └── schema.py       ← Validação dos dados baixados
│
├── templates/
│   └── index.html      ← Interface do painel web
│
└── tests/
    └── unit/           ← 128 testes automatizados
```

---

## 10. Perguntas frequentes

**P: O sistema opera automaticamente na corretora?**  
R: Não. O sistema apenas analisa e sugere — a decisão e a execução da ordem são sempre do usuário.

**P: Os sinais garantem lucro?**  
R: Não. Nenhuma análise técnica garante resultados. Use sempre stop loss e gerencie o risco.

**P: Por que os preços vêm do Yahoo Finance e não da B3?**  
R: O Yahoo Finance oferece dados gratuitos e suficientes para análise. Para dados em tempo real da B3 seria necessária uma assinatura de feed de dados.

**P: Posso adicionar outros ativos além de WIN e WDO?**  
R: Sim. Edite o dicionário `ASSETS` em `config.py` com o ticker correto do Yahoo Finance.

**P: O sistema funciona fora do horário do pregão?**  
R: Sim, mas os dados serão do último pregão encerrado. Sinais gerados fora do pregão devem ser confirmados na abertura do próximo dia.

**P: Os dados ficam salvos em algum lugar?**  
R: Sim. Os preços baixados ficam em cache temporário na pasta do projeto (arquivos `.pkl`) com validade entre 30 minutos e 48 horas dependendo do intervalo, economizando requisições ao Yahoo Finance.

**P: Como protejo o painel web se ele estiver acessível na rede?**  
R: Defina um token no `config.py` via variável de ambiente:
```bash
# Windows
$env:API_TOKEN = "uma-senha-longa-e-aleatoria"
# Linux/macOS
export API_TOKEN="uma-senha-longa-e-aleatoria"
```
Com isso, as rotas `/api/status` e `/api/signals` exigirão o token.

---

*Guia gerado em 16/04/2026 — versão correspondente ao commit da Fase 6.*
