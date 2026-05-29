# Manual do Usuário — Sistema `market_analysis`

**Versão**: 0.1.0 (pós-Sprint-17)
**Audiência**: Operadores, analistas, pesquisadores quantitativos, integradores
**Plataforma**: Windows / Linux / macOS — Python 3.10+
**Última revisão**: 2026-05-12

---

## Índice

1. [Instalação e configuração inicial](#1-instalação-e-configuração-inicial)
2. [Visão geral das ferramentas](#2-visão-geral-das-ferramentas)
3. [Ferramenta 1 — CLI principal (`run.py`)](#3-ferramenta-1--cli-principal-runpy)
4. [Ferramenta 2 — Dashboard CLI (`dashboard.py`)](#4-ferramenta-2--dashboard-cli-dashboardpy)
5. [Ferramenta 3 — Dashboard Web (`app.py`)](#5-ferramenta-3--dashboard-web-apppy)
6. [Ferramenta 4 — REST API (`api.py`)](#6-ferramenta-4--rest-api-apipy)
7. [Ferramenta 5 — Paper Trader (`paper_trader.py`)](#7-ferramenta-5--paper-trader-paper_traderpy)
8. [Ferramenta 6 — Scripts de análise (`scripts/`)](#8-ferramenta-6--scripts-de-análise-scripts)
9. [Configuração e parâmetros](#9-configuração-e-parâmetros)
10. [Fluxos de trabalho recomendados](#10-fluxos-de-trabalho-recomendados)
11. [Solução de problemas](#11-solução-de-problemas)
12. [Glossário](#12-glossário)

---

## 1. Instalação e configuração inicial

### 1.1 Requisitos

- Python 3.10 ou superior (testado em 3.10, 3.11, 3.12, 3.13)
- Conexão com internet (para download via yfinance)
- ~500 MB de espaço em disco (código + cache de dados típico)
- Para o dashboard web: porta 5000 livre

### 1.2 Instalação passo a passo

```bash
# 1. Clonar o repositório
cd H:\PYTHON
git clone <url-do-repo> market_analysis
cd market_analysis

# 2. Criar ambiente virtual
python -m venv venv

# 3. Ativar ambiente virtual
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# 4. Instalar dependências
pip install -e .          # instalação editable (recomendado para dev)
# ou
pip install -e .[dev]     # inclui pytest, ruff, mypy

# 5. Validar instalação
python -m pytest tests/unit -q
# Esperado: "519 passed in ~45s"
```

### 1.3 Dependências opcionais

Para usar a REST API:
```bash
pip install fastapi uvicorn pydantic
```

Para o meta-labeler ML:
```bash
pip install scikit-learn
```

Para otimização bayesiana:
```bash
pip install optuna
```

### 1.4 Configuração inicial

O arquivo `config.py` define os ativos padrão:

```python
ASSETS = {
    'IBOV':  {'ticker': '^BVSP',    'name': 'Ibovespa',    'decimal_places': 0},
    'BRL':   {'ticker': 'BRL=X',    'name': 'USD/BRL',     'decimal_places': 4},
    'PETR4': {'ticker': 'PETR4.SA', 'name': 'Petrobras',   'decimal_places': 2},
    'VALE3': {'ticker': 'VALE3.SA', 'name': 'Vale',        'decimal_places': 2},
}

DEFAULT_PERIOD = '6mo'       # janela de download
DEFAULT_INTERVAL = '1d'      # granularidade
LOG_LEVEL = 'INFO'           # DEBUG / INFO / WARNING / ERROR
```

Para alertas por e-mail, criar arquivo `.env` na raiz:
```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=seu@email.com
SMTP_PASS=senha_de_app
ALERT_TO=destinatario@email.com
```

---

## 2. Visão geral das ferramentas

O sistema oferece **seis modos de uso** complementares:

| Ferramenta | Tipo | Propósito | Quando usar |
|---|---|---|---|
| `run.py` | CLI | Análise/monitoramento/backtest/otimização | Operação diária via terminal |
| `dashboard.py` | CLI live | Painel texto em tempo real | Acompanhamento em terminal |
| `app.py` | Web | Dashboard HTTP + SocketIO | Visualização gráfica via navegador |
| `api.py` | REST | Endpoints HTTP JSON | Integração com sistemas externos |
| `paper_trader.py` | Library | Trading simulado persistido | Validar estratégia sem capital real |
| `scripts/*.py` | Scripts | Análises pontuais | Pesquisa, calibração, validação |

Cada ferramenta usa o mesmo núcleo (`strategy.py`, `indicators.py`, `backtester.py`) — escolha de interface não muda o modelo.

---

## 3. Ferramenta 1 — CLI principal (`run.py`)

### 3.1 Modos de execução

O `run.py` é o ponto de entrada unificado. Possui 4 modos:

#### 3.1.1 Análise única
Roda uma análise completa em todos os ativos configurados e mostra resultado no terminal.

```bash
python run.py
# (sem argumentos = modo análise única padrão)
```

**Saída típica:**
```
══════════════════════════════════════════════════════════════
  SISTEMA DE ANÁLISE DE MERCADO BRASILEIRO
  12/05/2026 14:32:18
══════════════════════════════════════════════════════════════

>>> ANÁLISE ÚNICA

──────────────────────────────────────────────────
  Ibovespa (^BVSP)
──────────────────────────────────────────────────
  Tendência:    Alta forte
  Último Preço: 138421
  RSI:          62.3
  ATR:          1247

  Sinais encontrados: 3
    • Compra | Breakout
      Preço: 138421 → Alvo: 142142 | Stop: 136680
    • Compra | EMA_Crossover
      ...
```

#### 3.1.2 Monitoramento contínuo
Loop infinito que reanalisa em intervalo configurável e dispara alertas em novos sinais.

```bash
python run.py monitor
# Roda a cada N segundos (config.MONITOR_INTERVAL, padrão 300s)
# CTRL+C para parar
```

Alertas são deduplicados por (ticker, tipo) com cooldown de 4h (configurável em `AlertProcessor.__init__(cooldown_seconds=14400)`).

#### 3.1.3 Backtest com parâmetros padrão
Roda backtest dos últimos 5 anos com a configuração default.

```bash
python run.py backtest
```

**Saída**: tabela de métricas (Retorno %, Sharpe, PF, MDD, Win Rate) por ativo, mais lista dos 10 últimos trades.

#### 3.1.4 Otimização
Executa grid search + walk-forward + reporta melhores parâmetros.

```bash
python run.py optimize
```

⚠️ **Atenção**: pode demorar 30min-3h dependendo do espaço de parâmetros. Resultado salvo em `best_params_<asset>.txt`.

### 3.2 Personalização

Para mudar a config padrão sem editar `config.py`, edite as variáveis de ambiente ou crie `config.local.py`:

```python
# config.local.py (não versionado)
ASSETS = {'TEST': {'ticker': 'AAPL', 'name': 'Apple', 'decimal_places': 2}}
DEFAULT_PERIOD = '1y'
```

---

## 4. Ferramenta 2 — Dashboard CLI (`dashboard.py`)

Painel texto em tempo real, sem dependências além do core.

### 4.1 Uso básico

```bash
python dashboard.py
# Mostra estado atual de ^BVSP
```

### 4.2 Argumentos

| Argumento | Padrão | Descrição |
|---|---|---|
| `--ticker TICKER` | `^BVSP` | Símbolo a monitorar (qualquer ticker yfinance) |
| `--optimized` | False | Carrega parâmetros otimizados de `best_params_<ticker>.txt` |
| `--refresh N` | 0 (uma vez) | Atualiza a cada N segundos |

### 4.3 Exemplos

```bash
# Dashboard estático de Petrobras
python dashboard.py --ticker PETR4.SA

# Dashboard live de Vale, atualiza a cada 60s
python dashboard.py --ticker VALE3.SA --refresh 60

# IBOV com parâmetros otimizados
python dashboard.py --optimized
```

### 4.4 Seções exibidas

1. **Status do mercado**: preço atual, tendência (Alta/Baixa/Lateral), ADX, Hurst, vol realizada
2. **Estado do meta-labeler**: treinado/não, ROC-AUC, top-5 features mais importantes
3. **Sinais ativos** (últimos N dias): tipo, estratégia, força, probabilidade meta
4. **Métricas de qualidade** (últimos 90 dias): PF, Sharpe, Win Rate, MDD
5. **Feature importance** (microestrutura + técnica)

---

## 5. Ferramenta 3 — Dashboard Web (`app.py`)

Interface web Flask + SocketIO para visualização gráfica em navegador.

### 5.1 Iniciar o servidor

```bash
python app.py
# Inicia em http://localhost:5000
```

Para acesso externo (cuidado com segurança):
```bash
python app.py --host 0.0.0.0 --port 5000
```

### 5.2 Endpoints disponíveis

| Endpoint | Método | Descrição |
|---|---|---|
| `/` | GET | Página principal (dashboard) |
| `/health` | GET | Healthcheck (retorna 200 OK) |
| `/api/status` | GET | Status atual em JSON |
| `/api/signals` | GET | Lista de sinais correntes |
| `/socket` | WS | Push real-time de atualizações |

### 5.3 Autenticação

Por padrão o `app.py` aceita conexões sem autenticação (apenas para uso local). Para produção, configurar Bearer token:

```python
# em app.py
AUTH_TOKEN = os.environ.get("APP_AUTH_TOKEN", None)
# Requisições devem incluir: Authorization: Bearer <token>
```

⚠️ **Não exponha o `app.py` à internet pública sem auth + HTTPS.**

### 5.4 Componentes visuais

- **Gráfico de preço**: candles + EMAs + Bollinger + sinais sobrepostos
- **Painel de indicadores**: RSI, MACD, ATR, ADX, Hurst em séries temporais
- **Tabela de sinais**: lista interativa com filtros por tipo/estratégia
- **Equity curve**: simulação do capital ao longo do tempo
- **Notificações live**: novos sinais aparecem sem refresh manual (SocketIO)

---

## 6. Ferramenta 4 — REST API (`api.py`)

API HTTP JSON para integração com outros sistemas (n8n, Zapier, MCP, n custom apps).

### 6.1 Iniciar o servidor

```bash
# Instalar fastapi se não tiver
pip install fastapi uvicorn

# Iniciar
uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

Documentação automática disponível em:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### 6.2 Endpoints

#### `GET /status`
Retorna estado do serviço.

```bash
curl http://localhost:8000/status
# {"status":"ok","version":"0.1.0","cache_entries":3}
```

#### `POST /signal`
Gera sinal corrente para um ticker.

```bash
curl -X POST http://localhost:8000/signal \
  -H "Content-Type: application/json" \
  -d '{"ticker":"^BVSP","period":"6mo","interval":"1d"}'
```

**Request body** (`SignalRequest`):
```json
{
  "ticker": "^BVSP",
  "period": "6mo",
  "interval": "1d",
  "params_override": {
    "use_regime_filter": true,
    "macro_direction_lock": true
  }
}
```

**Response** (`SignalOut`):
```json
{
  "ticker": "^BVSP",
  "signals": [
    {
      "data": "2026-05-12",
      "tipo": "Compra",
      "preco": 138421.0,
      "stop_loss": 136680.0,
      "preco_alvo": 142142.0,
      "estrategia": "Breakout",
      "forca": 8
    }
  ],
  "n_signals": 1,
  "generated_at": "2026-05-12T14:32:18Z"
}
```

#### `POST /backtest`
Executa backtest com parâmetros customizados.

```bash
curl -X POST http://localhost:8000/backtest \
  -H "Content-Type: application/json" \
  -d '{
    "ticker": "VALE3.SA",
    "period": "2y",
    "interval": "1d",
    "params_override": {
      "use_ensemble": true,
      "macro_direction_lock": true,
      "use_chandelier_after_be": true
    }
  }'
```

**Response** (`BacktestOut`):
```json
{
  "ticker": "VALE3.SA",
  "n_trades": 13,
  "profit_factor": 2.17,
  "return_pct": 1.21,
  "max_drawdown": 1.51,
  "sharpe_ratio": 1.29,
  "win_rate": 0.769,
  "trades_sample": [...]
}
```

#### `GET /metrics/{ticker}`
Métricas técnicas correntes (ADX, Hurst, RSI, etc.).

```bash
curl http://localhost:8000/metrics/^BVSP?period=2y
```

### 6.3 Cache

Respostas são cacheadas em memória por **300 segundos** por padrão. Para forçar refresh, mude o `period` ou parâmetros — chaves de cache incluem hash dos inputs.

### 6.4 Limitações conhecidas

- Cache é in-memory single-instance (não compartilhado entre workers)
- Sem rate limiting nativo (recomenda-se proxy reverso nginx/traefik)
- Sem autenticação built-in (adicionar middleware ou colocar atrás de API gateway)

---

## 7. Ferramenta 5 — Paper Trader (`paper_trader.py`)

Motor de trading simulado com persistência em disco. Usado tanto via biblioteca quanto em scripts.

### 7.1 Uso programático básico

```python
from paper_trader import PaperTrader
from strategy import CombinedStrategy
from data_provider import DataProvider

# 1. Inicializar trader
pt = PaperTrader(
    initial_capital=100_000.0,
    size_pct=0.50,              # 50% do equity por posição
    max_positions=3,             # até 3 posições simultâneas
    state_dir="./.paper_state",  # diretório de persistência
)

# 2. Carregar estratégia
strat = CombinedStrategy("^BVSP")
dp = DataProvider("^BVSP", interval="1d", period="6mo")
df = dp.fetch()
strat.set_data(df)
strat.params.update({
    "use_regime_filter": True,
    "macro_direction_lock": True,
    "use_partial_exit": True,
    "use_chandelier_after_be": True,
})

# 3. Atualizar trader com sinais correntes
last_close = float(df["Close"].iloc[-1])
result = pt.update(strat, current_price=last_close)
# Abre/fecha posições conforme sinais e regras de exit

# 4. Consultar estado
print(pt.metrics())
# {'equity': 102341.0, 'n_trades': 5, 'win_rate': 0.6, 'total_pnl': 2341.0, ...}

pt.print_summary()
# Mostra tabela de trades + posições abertas

# 5. Listar trades e posições
trades = pt.get_trades()
positions = pt.get_positions()
```

### 7.2 Persistência

Estado é salvo automaticamente em:
- `{state_dir}/.paper_positions.json` — posições abertas (round-trip via Position.to_dict/from_dict)
- `{state_dir}/paper_trades.json` — histórico completo de trades fechados

Para resetar:
```python
pt.reset()  # apaga arquivos e zera estado
```

### 7.3 Métodos principais

| Método | Função |
|---|---|
| `update(strategy, current_price)` | Loop principal: processa sinais, abre/fecha posições, salva estado |
| `open_position(sig, ticker)` | Abre posição respeitando `max_positions` e dedup por (ticker, side) |
| `close_position(pos, exit_price, reason)` | Fecha posição e registra trade |
| `check_exits(current_prices)` | Verifica stops/targets em todas as posições abertas |
| `metrics()` | Dict com equity, win_rate, total_pnl, n_trades, etc. |
| `equity_with_open(price_map)` | Equity incluindo PnL não-realizado |
| `print_summary()` | Imprime resumo formatado no console |
| `reset()` | Zera estado e remove arquivos persistidos |

### 7.4 Casos de uso

**Cenário A — Operação simulada diária:**
```python
# crontab @ 18h
pt = PaperTrader(state_dir="./prod_paper")
strat = build_strategy_sprint13()
pt.update(strat, current_price=latest_close)
send_email_report(pt.metrics())
```

**Cenário B — Validação A/B de configurações:**
```python
for label, params in [("baseline", {}), ("sprint13", SPRINT13_PARAMS)]:
    pt = PaperTrader(initial_capital=100_000, state_dir=f"./ab/{label}")
    # ... rodar mesma série temporal ...
    print(f"{label}: {pt.metrics()}")
```

---

## 8. Ferramenta 6 — Scripts de análise (`scripts/`)

Coleção de scripts standalone para análises pontuais. Todos são autoexecutáveis:

```bash
python scripts/<nome>.py
```

### 8.1 `fetch_real_data.py`
**Função**: utilitário de download yfinance com cache + retry + fallback.

```bash
# Não é executado diretamente; importado por outros scripts:
from scripts.fetch_real_data import download
df, source = download("^BVSP", "2020-01-01", "2024-01-01", interval="1d")
# source ∈ {'cache', 'yfinance', 'synthetic'}
```

### 8.2 `expected_return_analysis.py`
**Função**: comparativo das configurações de Sprint-2 a Sprint-13 com 3 metodologias:
- OOS único 70/30
- Walk-Forward 5-fold
- Monte Carlo (Bootstrap + GBM)

```bash
python scripts/expected_return_analysis.py
```

**Saída**: tabela comparativa formatada + análise textual da config eleita.

### 8.3 `walk_forward_real.py`
**Função**: walk-forward analysis com anchored ou sliding windows.

```bash
python scripts/walk_forward_real.py
```

**Saída**: PF, retorno, MDD, Sharpe por fold + agregado mediano.

### 8.4 `oos_final.py`
**Função**: validação final pós-otimização (sanity check antes de "deploy").

```bash
python scripts/oos_final.py
```

### 8.5 `optimize_optuna.py`
**Função**: otimização bayesiana com TPE.

```bash
pip install optuna
python scripts/optimize_optuna.py
# Salva melhores params em best_params_optuna_<ticker>.json
```

### 8.6 `sprint13_robustness.py`
**Função**: sweep cross-ticker do `chandelier_atr_mult` em 4 instrumentos.

```bash
python scripts/sprint13_robustness.py
```

**Output**: matriz ticker × parâmetro com Sharpe/PF/Ret.

### 8.7 `portfolio_sprint13.py`
**Função**: carteira agregada equal-weight + cenário com BRL=X adaptado.

```bash
python scripts/portfolio_sprint13.py
```

**Output**: métricas de carteira vs B&H 1/N benchmark.

### 8.8 `bear_market_validation.py`
**Função**: roda config Sprint-13 em 7 crashes históricos (GFC, COVID, 2022, 2015 BR).

```bash
python scripts/bear_market_validation.py
```

**Output**: tabela com B&H Ret/MDD vs Strat Ret/MDD por cenário + estatísticas agregadas.

### 8.9 `hybrid_strategy.py`
**Função**: avalia 5 alocações (0/30/50/70/100 % B&H) em 5 cenários mistos.

```bash
python scripts/hybrid_strategy.py
```

**Output**: mediana por alocação — demonstra empiricamente que estratégia pura > híbridos.

### 8.10 `bench_partial_exit.py` / `bench_time_filter.py`
**Função**: benchmark de impacto isolado de features individuais (ablation studies).

```bash
python scripts/bench_partial_exit.py
python scripts/bench_time_filter.py
```

---

## 9. Configuração e parâmetros

### 9.1 Onde estão os parâmetros

A fonte única de verdade é `CombinedStrategy.DEFAULT_PARAMS` em `strategy.py`. Para customizar:

```python
strat = CombinedStrategy("^BVSP")
strat.params.update({
    "use_regime_filter": True,
    "macro_direction_lock": True,
    # ... outros overrides
})
```

### 9.2 Parâmetros essenciais — referência rápida

#### Filtros e regimes
| Parâmetro | Default | Faixa | Significado |
|---|---|---|---|
| `use_regime_filter` | False | bool | Bloqueia sinais fora de regime trending |
| `adx_threshold` | 25.0 | 15-40 | ADX mínimo para sinal valer |
| `hurst_threshold` | 0.50 | 0.45-0.70 | Hurst mínimo |
| `macro_direction_lock` | False | bool | Bloqueia sinais contrários a trend macro |
| `macro_direction_window` | 60 | 30-120 | Janela retrospectiva (bars) |
| `macro_direction_ret_min` | 0.05 | 0.03-0.12 | Retorno acumulado mínimo para "confirmado" |
| `macro_direction_hurst_min` | 0.55 | 0.50-0.65 | Hurst médio mínimo |

#### Ensemble
| Parâmetro | Default | Faixa | Significado |
|---|---|---|---|
| `use_ensemble` | False | bool | Liga geradores adicionais |
| `ensemble_ema_cross` | True | bool | EMA crossover gerador |
| `ensemble_breakout` | True | bool | Breakout Donchian gerador |
| `ensemble_breakout_window` | 20 | 10-50 | Janela de máxima/mínima |
| `ensemble_fibonacci` | False | bool | Fibonacci gerador (opt-in) |

#### Position sizing
| Parâmetro | Default | Faixa | Significado |
|---|---|---|---|
| `max_position_pct` | 0.50 | 0.10-1.00 | Máx % do equity por posição |
| `max_risk_pct` | 0.02 | 0.005-0.05 | Máx risco em $ por trade |
| `use_vol_targeting` | False | bool | Escala posição por vol realizada |
| `vol_target_annual` | 0.15 | 0.10-0.25 | Vol anualizada alvo |
| `use_kelly_sizing` | False | bool | Aplica fração Kelly após histórico |
| `kelly_fraction` | 0.5 | 0.25-1.0 | Multiplicador de Kelly (half/full) |

#### Exits
| Parâmetro | Default | Faixa | Significado |
|---|---|---|---|
| `atr_stop_multiplier` | 1.5 | 1.0-3.0 | Stop em ATRs do entry |
| `atr_target_multiplier` | 3.0 | 2.0-5.0 | Take profit em ATRs do entry |
| `use_partial_exit` | False | bool | Fecha 50% em 1R + move BE |
| `partial_exit_r` | 1.0 | 0.5-2.0 | R-multiple para disparar partial |
| `use_trailing_stop` | False | bool | Trailing ATR após threshold |
| `use_chandelier_after_be` | False | bool | Chandelier após breakeven |
| `chandelier_atr_mult` | 3.0 | 1.5-5.0 | Distância em ATRs do peak |

#### Meta-labeler
| Parâmetro | Default | Significado |
|---|---|---|
| `use_meta_labeler` | False | Liga filtragem ML |
| `meta_min_prob` | 0.55 | Probabilidade mínima para passar |
| `meta_n_estimators` | 100 | Árvores no RandomForest |

### 9.3 Configurações de referência

#### Config "Baseline" (sem features avançadas)
```python
params = {}  # tudo no default
```

#### Config "Sprint-2" (regime + vol + ensemble)
```python
params = dict(
    use_regime_filter=True, adx_threshold=25.0, hurst_threshold=0.50,
    use_vol_targeting=True, vol_target_annual=0.15,
    use_ensemble=True, ensemble_ema_cross=True, ensemble_breakout=True,
)
```

#### Config "Sprint-13" — **RECOMENDADA**
```python
params = dict(
    # Regime e ensemble
    use_regime_filter=True, adx_threshold=25.0, hurst_threshold=0.50,
    use_vol_targeting=True, vol_target_annual=0.15,
    use_ensemble=True, ensemble_ema_cross=True, ensemble_breakout=True,
    # Macro direction lock
    macro_direction_lock=True, macro_direction_window=60,
    macro_direction_ret_min=0.08, macro_direction_hurst_min=0.55,
    # Exits
    use_partial_exit=True, partial_exit_r=1.0, partial_exit_fraction=0.5,
    breakeven_offset_atr=0.0,
    use_chandelier_after_be=True, chandelier_atr_mult=3.0,
)
```

**Métricas esperadas com Sprint-13** (em ações brasileiras, daily, OOS 6 meses):
- Profit Factor: 1.5-2.8
- Sharpe Ratio: 1.0-2.5
- Win Rate: 60-85%
- Max Drawdown: <2%
- Trades por mês: 1-3

---

## 10. Fluxos de trabalho recomendados

### 10.1 Fluxo "Analista quant" — pesquisa e validação

```bash
# 1. Validar instalação
python -m pytest tests/unit -q

# 2. Comparar configurações em ^BVSP
python scripts/expected_return_analysis.py

# 3. Validar generalização
python scripts/sprint13_robustness.py

# 4. Stress test com bears históricos
python scripts/bear_market_validation.py

# 5. Walk-forward profundo
python scripts/walk_forward_real.py

# 6. Otimização (opcional, pode demorar horas)
python scripts/optimize_optuna.py
```

### 10.2 Fluxo "Operador" — uso diário

```bash
# 1. Análise matinal (antes do pregão)
python dashboard.py --ticker ^BVSP --refresh 0
python dashboard.py --ticker VALE3.SA --refresh 0

# 2. Monitoramento durante o pregão
python run.py monitor &
# (alertas chegam por e-mail conforme configurado)

# 3. Revisão pós-pregão
python run.py backtest          # confere métricas com dados atualizados

# 4. Paper trading (registro de decisões hipotéticas)
python -c "from paper_trader import PaperTrader; pt = PaperTrader(); pt.print_summary()"
```

### 10.3 Fluxo "Integrador" — API + sistemas externos

```bash
# 1. Iniciar API
uvicorn api:app --host 0.0.0.0 --port 8000 &

# 2. Consumir em outro sistema
curl -X POST http://localhost:8000/signal -d '{"ticker":"^BVSP"}'

# 3. Webhook para Slack/Discord (exemplo)
# Configurar n8n / Make / Zapier para chamar /signal a cada 5min
# e postar resultado em canal
```

### 10.4 Fluxo "Pesquisador ML" — desenvolver novos sinais

```python
# 1. Instanciar estratégia com meta-labeler
from strategy import CombinedStrategy
strat = CombinedStrategy("^BVSP")
strat.set_data(df_train)
strat.params.update({
    "use_meta_labeler": True,
    "meta_min_prob": 0.55,
})
strat.prepare()

# 2. Treinar meta-labeler
strat.train_meta_labeler()
print(strat._meta_labeler.metrics)  # ROC-AUC, importances

# 3. Avaliar em OOS
strat_oos = CombinedStrategy("^BVSP")
strat_oos.set_data(df_test)
strat_oos.params.update(strat.params)
strat_oos._meta_labeler = strat._meta_labeler  # transfere modelo treinado
signals = strat_oos.generate_signals()

# 4. Backtest e métricas
from backtester import Backtester
bt = Backtester(strat_oos, initial_capital=100_000)
m = bt.run()
print(m)
```

### 10.5 Fluxo "Compliance/Auditoria"

```bash
# 1. Histórico completo de mudanças
git log --oneline --all

# 2. Cobertura de testes
pip install pytest-cov
pytest tests/unit --cov=. --cov-report=html
# Abre htmlcov/index.html

# 3. Reprodução de resultado histórico específico
git checkout <commit-do-sprint-X>
python scripts/expected_return_analysis.py > saida.txt

# 4. Análise estática de código
ruff check .
mypy --strict strategy.py backtester.py
```

---

## 11. Solução de problemas

### 11.1 Erros comuns

#### "ModuleNotFoundError: No module named 'fastapi'"
```bash
pip install fastapi uvicorn pydantic
```

#### "yfinance returned empty DataFrame"
- Verifique o ticker (deve seguir convenção Yahoo: `^BVSP`, `PETR4.SA`, `BRL=X`)
- Verifique conexão com internet
- yfinance pode ter rate limit — aguarde 1-2 minutos

#### "All signals filtered out"
- Provavelmente `use_regime_filter=True` em mercado lateral
- Tente desligar filtros um a um para diagnóstico
- Use `logger.setLevel(logging.DEBUG)` para ver detalhes

#### "Meta-labeler not trained"
- Requer histórico mínimo (~100 trades)
- Verifique se `prepare()` foi chamado antes
- Confirme que `sklearn` está instalado

#### "Paper trader state corrupted"
```python
pt.reset()  # cuidado: apaga histórico
```

### 11.2 Performance / lentidão

| Sintoma | Causa provável | Solução |
|---|---|---|
| Backtest > 30s para 1 ano daily | Indicadores recalculados | Verifique se `prepare()` é chamado uma vez só |
| Walk-forward > 10min | Espaço de parâmetros grande | Reduza grid ou use Optuna |
| API respondendo lenta | Cache miss | Confirme cache TTL e chave de cache |
| yfinance download lento | Rate limit | Use cache local (já implementado) |

### 11.3 Validação de integridade

Sempre após mudança grande:
```bash
python -m pytest tests/unit -q    # 519/519 deve passar
ruff check .                       # lint
python scripts/expected_return_analysis.py  # smoke test econômico
```

---

## 12. Glossário

| Termo | Definição |
|---|---|
| **ADX** | Average Directional Index — força da tendência (0-100) |
| **ATR** | Average True Range — proxy de volatilidade absoluta |
| **B&H** | Buy-and-Hold — manter posição estática |
| **Breakeven (BE)** | Ponto de equilíbrio = preço de entrada |
| **CAGR** | Compound Annual Growth Rate |
| **Calmar Ratio** | Retorno anualizado / Max Drawdown |
| **Chandelier Exit** | Trailing stop baseado em peak high - N×ATR |
| **CVaR** | Conditional Value at Risk — perda esperada além do VaR |
| **DSR** | Deflated Sharpe Ratio — Sharpe corrigido por multiple testing |
| **Hurst Exponent** | Persistência da série; >0.5 trending, <0.5 mean-reverting |
| **IS / OOS** | In-Sample / Out-of-Sample |
| **Kelly Criterion** | Fração ótima a apostar dado win rate e payoff ratio |
| **MDD** | Maximum Drawdown — maior queda do pico ao vale |
| **Meta-labeler** | Classificador secundário que filtra sinais primários |
| **PF** | Profit Factor — sum(wins) / abs(sum(losses)) |
| **Purged K-Fold** | K-Fold com embargo temporal para evitar leakage |
| **R-multiple** | Múltiplos de risco inicial; 1R = lucro = risco |
| **Sharpe Ratio** | (Retorno - taxa livre) / Volatilidade |
| **Sortino Ratio** | Sharpe usando downside deviation |
| **Triple-Barrier** | Labeling com 3 barreiras: TP, SL, timeout |
| **VaR** | Value at Risk — perda no percentil X (ex: 95%) |
| **Walk-Forward** | Validação rolante IS → OOS sequencial |

---

## Apêndices

### A. Atalhos de execução

```bash
# Suite completa de validação (~3-5 min)
python -m pytest tests/unit -q && \
python scripts/expected_return_analysis.py && \
python scripts/bear_market_validation.py

# Setup operação diária
python dashboard.py --ticker ^BVSP --refresh 300 &
python run.py monitor &

# Build de produção (API)
uvicorn api:app --host 0.0.0.0 --port 8000 --workers 4
```

### B. Estrutura de diretórios

```
market_analysis/
├── *.py                    # módulos core (strategy, backtester, etc.)
├── scripts/                # análises pontuais executáveis
├── tests/unit/             # 519 testes (45s para rodar tudo)
├── venv/                   # ambiente virtual (gitignored)
├── .cache/                 # cache de dados yfinance (gitignored)
├── pyproject.toml          # configuração do pacote
├── RELATORIO_TECNICO.md    # documentação técnica completa
└── MANUAL_USUARIO.md       # este arquivo
```

### C. Referências bibliográficas

- López de Prado, M. *Advances in Financial Machine Learning* (2018) — Triple-Barrier, Purged K-Fold
- Bailey, D. & López de Prado, M. *The Deflated Sharpe Ratio* (2014)
- Wilder, J. W. *New Concepts in Technical Trading Systems* (1978) — RSI, ATR, ADX
- Le Baron, A. *Chandelier Exit* — Active Trader Magazine
- Mandelbrot, B. *The Variation of Certain Speculative Prices* (1963) — Hurst Exponent

### D. Suporte e contato

- Issues: `git log --oneline` para histórico, ou GitHub Issues do repositório
- Documentação técnica detalhada: `RELATORIO_TECNICO.md`
- Testes como exemplos canônicos: `tests/unit/test_*.py`

---

**Fim do Manual do Usuário.**
*Para questões metodológicas, consulte o `RELATORIO_TECNICO.md`. Para o histórico evolutivo, `git log --all`.*
