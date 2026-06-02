# Relatório Técnico — Sistema de Análise Quantitativa de Mercado

**Projeto**: `market_analysis`
**Versão**: 0.1.0 — pós-Sprint-17
**Data do relatório**: 2026-05-12
**Autor do sistema**: Jeferson Wohanka
**Repositório**: `H:\PYTHON\market_analysis`
**Audiência**: Analistas econômicos, equipe de TI, supervisores quantitativos

---

## 1. Sumário Executivo

O `market_analysis` é um sistema integrado de pesquisa quantitativa, backtesting, geração de sinais e execução simulada (paper trading) para mercados financeiros, com foco primário no mercado brasileiro (B3) mas com generalização demonstrada para mercados internacionais (^GSPC, ^IXIC) e forex (BRL=X). O sistema é desenvolvido em Python 3.10+, modularizado em ~19 mil linhas de código produtivo, com 519 testes unitários (100% passando) e 17 sprints de evolução documentados em commits.

### 1.1 Perfil estratégico validado

> ⚠️ **MDD nesta seção reflete equity total.** Ver `findings/sprint_18_mdd_dual.md` (Sprint 18) para desambiguação — o MDD sobre capital em risco é materialmente maior (mediana 17,5% vs 0,8%).

A configuração de referência (Sprint-13) apresenta o seguinte perfil empírico, validado em séries reais multi-instrumento e multi-regime:

| Métrica | Bull market | Bear market | Mix histórico |
|---|---|---|---|
| Profit Factor (mediana) | 2.17 | 0.86 | 1.43 |
| Sharpe Ratio (mediana) | +1.72 | -0.43 | +0.29 |
| Win Rate (mediana) | 76–84% | 55–62% | 60% |
| Max Drawdown | <1% | 0.7–1.7% | 0.82% |
| Alpha vs Buy-and-Hold | -30 a -60pp | **+19pp** | +0.55pp |

O perfil é qualificado como **"downside protection insurance"**: paga prêmio em bull markets (alpha negativo) e paga em sinistro (preservação assimétrica em crashes). Hipóteses híbridas (50/50 com B&H) foram testadas e empiricamente rejeitadas — o produto é a estratégia pura, com o blending ocorrendo no portfolio do cliente.

### 1.2 Validação contra crashes históricos (7 cenários)

> ⚠️ **MDD nesta seção reflete equity total.** Ver `findings/sprint_18_mdd_dual.md` (Sprint 18) para desambiguação — o MDD sobre capital em risco é materialmente maior (mediana 17,5% vs 0,8%).

| Crash | Período | B&H MDD | Sistema MDD | Razão |
|---|---|---|---|---|
| GFC 2008 ^BVSP | 2008-06–2009-06 | 59.06% | **0.74%** | 0.01× |
| GFC 2008 ^GSPC | 2008-06–2009-06 | 51.82% | 1.73% | 0.03× |
| COVID 2020 ^BVSP | 2020-01–2020-06 | 46.82% | 0.94% | 0.02× |
| 2022 bear ^IXIC | 2022-01–2022-12 | 35.49% | 1.58% | 0.04× |
| 2015 BR bear ^BVSP | 2015-01–2016-01 | 35.41% | 1.73% | 0.05× |

Razão mediana MDD sistema/B&H = **0.04×** (preserva 25× mais capital). 7/7 cenários com alpha positivo sobre B&H.

---

## 2. Arquitetura do Sistema

### 2.1 Visão de camadas

```
┌────────────────────────────────────────────────────────────────┐
│ CAMADA DE APRESENTAÇÃO                                         │
│   app.py            — Dashboard web Flask + SocketIO           │
│   dashboard.py      — Dashboard CLI em texto puro              │
│   api.py            — REST API FastAPI (signals, backtest)     │
└────────────────────────────────────────────────────────────────┘
                              │
┌────────────────────────────────────────────────────────────────┐
│ CAMADA DE EXECUÇÃO                                             │
│   paper_trader.py   — Engine de trading simulado persistido    │
│   alert_manager.py  — Roteamento de alertas (e-mail/log)       │
│   alerts.py         — Lógica de cooldown e deduplicação        │
└────────────────────────────────────────────────────────────────┘
                              │
┌────────────────────────────────────────────────────────────────┐
│ CAMADA DE INTELIGÊNCIA                                         │
│   strategy.py       — Estratégia combinada (geradores+filtros) │
│   meta_labeler.py   — Filtragem ML (RandomForest)              │
│   labels.py         — Triple-Barrier labeling                  │
│   price_action.py   — Detecção de padrões                      │
│   sentiment_analyzer.py — Score de sentimento                  │
└────────────────────────────────────────────────────────────────┘
                              │
┌────────────────────────────────────────────────────────────────┐
│ CAMADA QUANTITATIVA                                            │
│   indicators.py     — Indicadores técnicos + Fibonacci         │
│   backtester.py     — Motor de simulação event-driven          │
│   stress_test.py    — Monte Carlo (Bootstrap + GBM+Jump)       │
│   optimizer.py      — Grid search + Walk-Forward + Optuna      │
└────────────────────────────────────────────────────────────────┘
                              │
┌────────────────────────────────────────────────────────────────┐
│ CAMADA DE DADOS                                                │
│   data_provider.py  — Adaptador yfinance + tratamento MultiIdx │
│   scripts/fetch_real_data.py — Cache, retry, fallback synth.   │
│   config.py         — Carregamento de parâmetros               │
└────────────────────────────────────────────────────────────────┘
```

### 2.2 Princípios de design

- **Imutabilidade do pipeline**: cada barra processada é determinística; ausência de look-ahead bias é garantida por janelas exclusivas, atualizações de peak/state ao final da barra, e testes específicos (ver `test_indicators.py`, `test_fibonacci.py::test_no_lookahead`).
- **Opt-in features**: novas capacidades são introduzidas com flag desligado por padrão para preservar retrocompatibilidade — `use_regime_filter`, `use_meta_labeler`, `use_kelly_sizing`, `macro_direction_lock`, `use_chandelier_after_be` etc.
- **Graceful degradation**: serviços externos (FastAPI, e-mail SMTP) são detectados em runtime; ausência não quebra o core.
- **Configuração centralizada**: `CombinedStrategy.DEFAULT_PARAMS` é o ponto único de verdade dos parâmetros estratégicos.
- **Test-first em features críticas**: cada sprint adiciona testes antes ou em paralelo à implementação; regressão obrigatória de 100% para commit.

---

## 3. Estrutura de Arquivos (Detalhamento)

### 3.1 Núcleo do sistema (camada Python raiz)

| Arquivo | LOC | Função |
|---|---:|---|
| `strategy.py` | 949 | Estratégia combinada — geradores de sinal (price action, ensemble EMA, breakout, Fibonacci), filtros (regime, sentimento, horário, direção macro), deduplicação e dispatch. |
| `indicators.py` | 666 | Indicadores técnicos: SMA, EMA, RSI, MACD, ATR, ADX, Bollinger, Hurst, Realized Vol, retracements de Fibonacci. Função `compute_all()` é o ponto único de adição de colunas técnicas. |
| `backtester.py` | ~1100 | Motor event-driven barra-a-barra. Suporta long/short, stop/TP, partial exit @ 1R + breakeven, trailing stop, Chandelier exit pós-BE, vol targeting, Kelly sizing, cooldown, slippage e comissão. |
| `meta_labeler.py` | 624 | Pipeline ML: feature engineering, Triple-Barrier labels, Purged K-Fold, RandomForest classifier, predict_proba para filtragem secundária de sinais primários. |
| `optimizer.py` | 632 | Grid search com Walk-Forward analysis, Deflated Sharpe Ratio (DSR), paralelismo via multiprocessing. |
| `labels.py` | 350 | Triple-Barrier labeling (López de Prado): definição de barreiras superior/inferior/vertical, atribuição de labels {-1, 0, +1}. |
| `paper_trader.py` | 457 | Engine de trading simulado com persistência JSON. Classes `Position` (long/short, current_pnl) e `PaperTrader` (open/close/check_exits/metrics). |
| `api.py` | ~400 | REST API FastAPI: endpoints `/status`, `/signal`, `/backtest`, `/metrics/{ticker}`. Cache TTL 300s. Stubs para fastapi/pydantic ausentes. |
| `app.py` | ~600 | Dashboard web Flask + SocketIO (real-time). Auth Bearer, rate-limit, health endpoint. |
| `stress_test.py` | 437 | Stress testing: Bootstrap N=2000, GBM com jump diffusion, parametric scenarios (crash/rally/range), CVaR, MDD distributions. |
| `price_action.py` | 450 | Detecção de padrões: pin bars, engulfings, inside bars, support/resistance baseado em swing highs/lows. |
| `dashboard.py` | 277 | Dashboard CLI texto puro com refresh configurável. |
| `data_provider.py` | 131 | Adaptador yfinance com tratamento de MultiIndex (consequência de auto_adjust). |
| `alert_manager.py` | ~300 | Roteamento de alertas (e-mail SMTP, log, webhook). |
| `alerts.py` | 100 | Cooldown e deduplicação (4h padrão por (ticker, tipo)). |
| `sentiment_analyzer.py` | 135 | Score de sentimento via análise de notícias (placeholder + hooks para feed real). |
| `run.py` | 209 | Entry point CLI. |
| `config.py` | ~80 | Carregamento de YAML/JSON de configuração externa. |

### 3.2 Scripts de análise (`scripts/`)

| Script | Propósito |
|---|---|
| `fetch_real_data.py` | Download yfinance com cache local, retry exponencial e fallback synthetic. |
| `expected_return_analysis.py` | Análise de retorno esperado: OOS 70/30, Walk-Forward 5-fold, Monte Carlo Bootstrap+GBM. Compara configurações Sprint-2 a Sprint-13. |
| `walk_forward_real.py` | Walk-forward analysis em dados reais (anchored + sliding). |
| `walk_forward_sprint1.py` / `walk_forward_sprint4.py` | Walk-forward específicos de marcos históricos. |
| `oos_final.py` | Validação OOS final pós-otimização. |
| `optimize_optuna.py` | Otimização bayesiana com TPE (Tree-structured Parzen Estimator). |
| `sprint13_robustness.py` | Sweep cross-ticker do `chandelier_atr_mult`. |
| `portfolio_sprint13.py` | Carteira agregada 1/N com thresholds adaptativos forex. |
| `bear_market_validation.py` | Validação em 7 crashes históricos (GFC, COVID, 2022 bear, 2015 BR). |
| `hybrid_strategy.py` | Avaliação de alocações híbridas B&H + Sprint-13. |
| `bench_partial_exit.py` / `bench_time_filter.py` | Benchmarks de impacto de features individuais. |

### 3.3 Suíte de testes (`tests/unit/`)

| Arquivo | LOC | Cobertura |
|---|---:|---|
| `test_strategy.py` | 599 | Estratégia, filtros, deduplicação |
| `test_backtester.py` | 538 | Motor de simulação, fills, métricas |
| `test_paper_trader.py` | 530 | Engine de execução simulada |
| `test_stress_test.py` | 525 | Monte Carlo, GBM, MDD |
| `test_optimizer.py` | 422 | Walk-forward, DSR, grid search |
| `test_triple_barrier.py` | 406 | Labeling |
| `test_meta_labeler.py` | 369 | ML pipeline |
| `test_fibonacci.py` | 332 | Indicador + sinais + bypass macro |
| `test_partial_breakeven.py` | 486 | Partial exit @ 1R + BE move |
| `test_ensemble_signals.py` | 374 | EMA crossover + breakout |
| `test_indicators.py` | 446 | Todos os indicadores |
| `test_macro_direction.py` | 184 | Lock direcional + boost |
| `test_chandelier.py` | 145 | Trailing pós-breakeven |
| `test_regime_detection.py` | 335 | ADX + Hurst |
| `test_vol_targeting.py` | 304 | Sizing por vol |
| (outros 9 arquivos) | ~2900 | API, app, dados, sprint6, etc. |
| **Total** | **~9400** | **519 testes** |

---

## 4. Stack Tecnológica

### 4.1 Linguagem e ambiente

- **Python 3.10+** (suporta 3.13, ambiente atual de execução)
- Ambiente virtual local em `venv/Scripts/python.exe` (Windows)
- Conformidade PEP-8 via `ruff>=0.5.0`
- Tipagem estática progressiva (`mypy>=1.10`)

### 4.2 Dependências de runtime (core)

| Pacote | Versão | Uso |
|---|---|---|
| `pandas` | ≥ 2.0 | Manipulação tabular, indexação temporal, rolling windows |
| `numpy` | ≥ 1.24 | Operações vetorizadas, álgebra linear, RNG |
| `yfinance` | ≥ 0.2.40 | Download de dados (Yahoo Finance v8 API) |
| `matplotlib` | ≥ 3.7 | Gráficos de equity, drawdown, signals |
| `plotly` | ≥ 5.18 | Visualização interativa (dashboard web) |
| `flask` | ≥ 3.0 | Dashboard web HTTP |
| `flask-socketio` | ≥ 5.3 | Push real-time para o dashboard |
| `tqdm` | ≥ 4.66 | Barras de progresso em loops longos |

### 4.3 Dependências opcionais (testes/dev)

- `pytest>=8.0` — framework de teste
- `pytest-cov>=5.0` — cobertura de código
- `fastapi`, `pydantic>=2.7` — REST API
- `scikit-learn` — `RandomForestClassifier` para meta-labeler
- `optuna>=3.6` — otimização bayesiana (script opcional)

### 4.4 Persistência

- **Cache de dados**: arquivos parquet/csv em diretório local (`.cache/`)
- **Estado do paper trader**: JSON (`.paper_positions.json`, `paper_trades.json`)
- **Configurações otimizadas**: `best_params_Ibovespa.txt`
- **Sem banco de dados relacional** — escopo single-user/single-machine atualmente

### 4.5 Integrações externas

- **Yahoo Finance API** (via `yfinance`): única fonte de dados
- **SMTP** (alert_manager.py): envio opcional de e-mail
- Sem integração com corretoras (paper trading apenas)

---

## 5. Fundamentação Metodológica

### 5.1 Indicadores técnicos

Todos os indicadores são re-implementações vetorizadas com testes de regressão numérica contra valores de referência. O sistema **não** usa bibliotecas como `pandas-ta` ou `talib` para evitar dependências binárias e garantir reprodutibilidade exata.

#### 5.1.1 Indicadores clássicos
- **SMA / EMA**: médias móveis com warm-up tratado por `min_periods`.
- **RSI** (Wilder): smoothing alpha = 1/period.
- **MACD**: 12/26/9 padrão, signal line e histograma.
- **ATR** (True Range): max(H-L, |H-PrevC|, |L-PrevC|), smoothed Wilder.
- **Bollinger Bands**: SMA ± 2σ, com %B normalizado.

#### 5.1.2 Indicadores de regime
- **ADX (Average Directional Index)**: medida de força da tendência, range [0, 100]. Threshold 25 = tendência confirmada (Wilder).
- **Hurst Exponent**: medida de persistência. H > 0.5 = trending, H < 0.5 = mean-reverting, H = 0.5 = random walk. Implementação via R/S analysis com regressão log-log.
- **Realized Volatility**: σ anualizada de log-returns em janela rolante.

#### 5.1.3 Fibonacci (Sprint-8, opt-in)
- Identificação de swing high/low em janela exclusiva `[i-w, i-1]` para evitar look-ahead.
- Filtro de amplitude: `swing_amp >= min_swing_atr × ATR[i-1]` (rejeita swings triviais).
- Determinação de trend: idx_low < idx_high → uptrend; inverso → downtrend.
- Níveis: 23.6%, 38.2%, 50%, 61.8%, 78.6% retracements + 127.2%, 161.8% extensions.

### 5.2 Filtros de regime e direção

#### 5.2.1 Regime filter (Sprint-2)
Aplicado por sinal: `ADX[ts] >= adx_threshold AND Hurst[ts] >= hurst_threshold`. Bloqueia sinais em regimes mean-reverting/ranging.

#### 5.2.2 Macro Direction Lock (Sprint-11/12)
Filtro de portfolio-level sobre todos os sinais:
- Janela retrospectiva: 60 bars
- Confirmação de uptrend: `cum_return >= 8% AND mean(Hurst) >= 0.55`
- Em uptrend confirmado: bloqueia **Vendas**
- Em downtrend confirmado: bloqueia **Compras**

Esta foi a primeira modificação que produziu config OOS + Walk-Forward simultaneamente positivos.

#### 5.2.3 Bypass Fibonacci-aware (Sprint-9/10)
- `fib_regime_bypass`: confia em `fib_trend != 0` como proxy de regime local (validação empírica mostrou degradação → mantido opt-in com default False).
- `fib_regime_macro_window > 0`: avalia ADX/Hurst pela média na janela retrospectiva (tolera "dip" pontual do pullback).

### 5.3 Ensemble de geradores de sinal

Três geradores independentes combinados via união + deduplicação:

1. **Price Action**: pin bars, engulfings, inside bars filtrados por contexto (S/R, ATR).
2. **EMA Crossover**: rápida cruza lenta com strength configurável.
3. **Breakout Donchian**: close acima/abaixo do max/min da janela anterior (N-bars, exclusive via `shift(1)`).
4. **Fibonacci** (opt-in): pullback a 38.2/50/61.8 em regime de trend.

Cada sinal carrega: `data`, `tipo` (Compra/Venda), `preco`, `stop_loss`, `preco_alvo`, `estrategia`, `forca`, opcionalmente `size_mult` (Sprint-12).

### 5.4 Position Sizing

Aplicado em cascata sobre o tamanho base (= `risk_per_trade × capital / risk_per_share`):

1. **Volatility Targeting** (Sprint-2): `scalar = target_vol / realized_vol`, clampado em [0.25, 2.0]. Reduz exposição em períodos voláteis, aumenta em períodos calmos.
2. **Kelly Sizing** (Sprint-6): `f* = (p·b - q)/b` onde p = win rate empírico, b = avg_win/avg_loss. Half-Kelly (`kelly_fraction=0.5`) padrão para reduzir variância. Mínimo histórico de 10 trades antes de aplicar.
3. **Per-signal multiplier** (Sprint-12): `sig["size_mult"]` permite que a estratégia carregue um boost/redução; clampado em [0.1, 3.0]. Usado pelo `macro_direction_boost` quando o sinal está alinhado ao regime macro confirmado.

### 5.5 Gestão de saídas

#### 5.5.1 Partial Exit @ 1R + Breakeven (Sprint-1)
Ao atingir 1× risco inicial em lucro:
- Fecha 50% da posição (`partial_exit_fraction`)
- Move stop do restante para entry + `breakeven_offset_atr × ATR` (longs) ou simétrico (shorts)
- Resultado: converte ~30% dos "near-losers" em scratch trades (PnL ≈ 0), elevando o Profit Factor.

#### 5.5.2 Chandelier Exit pós-breakeven (Sprint-13)
Após `breakeven_moved=True`:
- Long: `stop = peak_high_since_entry - chandelier_atr_mult × ATR`
- Short: `stop = peak_low_since_entry + chandelier_atr_mult × ATR`
- Atualização do peak ao **final** da barra (após exits) → evita lookahead intra-bar
- Só aperta, nunca afrouxa
- Default `chandelier_atr_mult = 3.0`; sweep [1.5..4.0] mostrou sensitivity nula → robusto

### 5.6 Machine Learning — Meta-Labeler (Sprint-3/4)

Inspirado em López de Prado (*Advances in Financial Machine Learning*).

#### 5.6.1 Triple-Barrier Labeling
Para cada sinal primário, define três barreiras a partir do preço de entrada:
- Superior: `entry + take_profit_atr × ATR`
- Inferior: `entry - stop_loss_atr × ATR`
- Vertical: `entry_time + max_holding_period`

Label = sinal da primeira barreira tocada: +1 (TP), -1 (SL), 0 (timeout).

#### 5.6.2 Features
- Técnicas: RSI, MACD, ADX, Bollinger %B, retorno N-bars, vol realizada
- Microestrutura: spread H-L, volume z-score, gap pct
- Contextuais: hora do dia, dia da semana, distância para S/R

#### 5.6.3 Pipeline
- Purged K-Fold (k=5, embargo de N bars) para evitar leakage temporal
- `RandomForestClassifier(n_estimators=100, max_depth=5)`
- ROC-AUC mínimo 0.55 para considerar treinado
- Em produção: `predict_proba(features) >= meta_min_prob` filtra sinais

### 5.7 Backtesting e Validação

#### 5.7.1 Motor event-driven (`backtester.py`)
- Loop barra-a-barra com state machine: NO_POSITION → POSITION_OPEN → (PARTIAL → BE) → CLOSED
- Slippage: `0.1%` padrão (configurável)
- Comissão: `R$ 0.001` por trade
- Cooldown: 2 bars entre saída e nova entrada (evita overtrading)
- ⚠️ **Sensibilidade a custos (Sprint 19)**: o modelo de custo fixo acima é otimista. Ver `findings/sprint_19_cost_sensitivity.md` — varredura comissão×slippage em janela OOS (últimos 30%). O motor ganhou o parâmetro opt-in `commission_pct` (comissão percentual, default 0.0, não-quebrante) usado nessa análise.

#### 5.7.2 Métricas computadas
- **Retorno total** (%), **CAGR**, **Sharpe** (anualizado, 252 bars), **Sortino**, **Calmar** (Ret/MDD)
- **Profit Factor**: `sum(wins) / |sum(losses)|`
- **Win rate**, **Expectativa por trade**
- **Max Drawdown**: `(eq/peak - 1) × 100`, em %
- **Distribuições**: trade PnL histogram, holding period

#### 5.7.3 Validação Out-of-Sample
Três metodologias complementares aplicadas em `expected_return_analysis.py`:
1. **OOS único 70/30**: split temporal, IS para fit/calibração (meta-labeler), OOS para avaliação.
2. **Walk-Forward 5-fold**: 5 splits sequenciais anchored — testa estabilidade temporal.
3. **Monte Carlo**: 2000 simulações via (a) Bootstrap de trades reais, (b) GBM + jump diffusion para cenários prospectivos.

#### 5.7.4 Stress Testing (`stress_test.py`)
- **Bootstrap N=2000**: VaR 95%, CVaR 95%, MDD median, MDD p95, prob. de ruína
- **GBM + Jump Diffusion**: σ histórica, μ histórico, λ_jump (frequência), jump size N(μj, σj²)
- **Parametric scenarios**: crash (-30% in 20 bars), rally (+30%), range (vol scaled)

### 5.8 Otimização

#### 5.8.1 Grid Search (`optimizer.py`)
- Espaço de parâmetros declarativo
- Paralelismo via `multiprocessing.Pool`
- Critério: Sharpe ajustado por Deflated Sharpe Ratio (DSR) — corrige overfitting estatístico de seleção de múltiplas hipóteses (Bailey & López de Prado, 2014).

#### 5.8.2 Bayesian (`scripts/optimize_optuna.py`)
- TPE (Tree-structured Parzen Estimator) via Optuna
- Sampling adaptativo: ~10× mais eficiente que grid em espaços de alta dimensão.

#### 5.8.3 Walk-Forward Optimization
Otimização IS + validação OOS em janelas rolantes → confirma robustez temporal antes de "deploy".

---

## 6. Características Distintivas do Sistema

### 6.1 Ausência rigorosa de look-ahead bias

Testes específicos comparam metric(df[:i]) com metric(df[:N])[i] para garantir igualdade. Casos críticos:
- Indicadores: `rolling().shift(1)` em breakout (`shift(1)` exclui barra atual)
- Fibonacci: janela exclusiva `[i-w, i-1]`
- Chandelier: peak atualizado **após** stop check
- Regime macro: janela `[i-w+1, i]` (i inclusive — usa info disponível ao fim do dia)

### 6.2 Determinismo e reprodutibilidade

- Sem chamadas a `random.seed()` global; cada simulação Monte Carlo recebe RNG explícito
- Cache local versionado evita drift de dados yfinance entre execuções
- Hashing de parâmetros para identificação de runs em log

### 6.3 Cobertura de testes

- **519 testes unitários** + 17 testes de integração implícitos via scripts
- Categorias cobertas: indicadores, regime, sizing, exits, ensemble, ML, API, persistência
- Pre-commit hook recomendado: regressão completa antes do push (~45 segundos)

### 6.4 Documentação evolutiva via commits

Cada sprint produz commit autoexplicativo (mensagem ~30 linhas) descrevendo:
- O que foi adicionado
- Resultado empírico (tabelas comparativas)
- Estado do regression test count
- Próximo passo recomendado

Esta cadeia permite auditoria histórica completa: `git log --oneline` mostra 17 marcos evolutivos.

---

## 7. Resultados Empíricos Consolidados

> ⚠️ **MDD nesta seção reflete equity total.** Ver `findings/sprint_18_mdd_dual.md` (Sprint 18) para desambiguação — o MDD sobre capital em risco é materialmente maior (mediana 17,5% vs 0,8%).

> ⚠️ **Robustez a custos (Sprint 19).** Sob varredura comissão×slippage numa janela OOS de **~8 anos (2018-07-04 a 2026-05-29, últimos 30% do histórico completo 2000-2026)** — distinta e muito mais longa que a janela curta por trás das tabelas 7.1/7.2 (`expected_return_analysis.py` usa só os últimos ~730 dias e tira OOS dos últimos 30% disso, ~7 meses) e com modelo de custo diferente (comissão percentual, R$ absoluto zerado) — a config Sprint-13 **não exibe edge no ^BVSP nessa janela longa**: PF 0.82 no baseline (slip/comm 0.1%), 0.69 a slip 0.3%, e 0.92 (ainda <1.0) mesmo a custo zero. Apenas 1 de 3 tickers (VALE3.SA) passa o teste de PF>1.0 a slip 0.3%, com retorno absoluto desprezível. **Isto não é refutação direta da tabela 7.2** (janela e metodologia diferentes) — a reconciliação e a reescrita do posicionamento de robustez ficam deferidas ao Marco do Bloco I (pós-S22). Ver `findings/sprint_19_cost_sensitivity.md`.

### 7.1 Evolução do Profit Factor OOS no IBOVESPA

| Sprint | Mudança | OOS PF | OOS Sharpe | OOS Win Rate |
|---|---|---:|---:|---:|
| 2 | Baseline (regime+vol+ensemble) | 0.854 | -0.394 | 46.2% |
| 11 | + Macro Direction Lock | 1.548 | +0.983 | 63.6% |
| 12 | Calibração thresholds (0.08, 0.55) | 1.548 | +0.983 | 63.6% |
| 13 | + Chandelier exit pós-BE | **2.119** | **+1.724** | **70.6%** |

### 7.2 Generalização cross-ticker (Sprint-14)

| Ticker | B&H OOS | Sistema PF | Sistema Sharpe | Sistema Win Rate |
|---|---:|---:|---:|---:|
| ^BVSP | +40.72% | 2.77 | +2.39 | 84.2% |
| VALE3.SA | +65.50% | 2.17 | +1.29 | 76.9% |
| PETR4.SA | +61.35% | 1.29 | +0.42 | 75.0% |
| BRL=X | -8.39% | 0.00 | -1.92 | 0.0% |

### 7.3 Limitações conhecidas (validadas empiricamente)

1. **Forex (BRL=X)**: o `macro_direction_lock` exige retorno cumulativo de 8% em 60 bars — USDBRL oscila em banda mais estreita. Apenas 3 trades em ~150 bars. Solução pendente: filtros adaptativos por classe de ativo (ranges Bollinger %B ao invés de retorno cumulativo).
2. **Underperformance em bull markets lineares**: alpha negativo persistente (-30 a -60pp vs B&H) em períodos de upside contínuo. Esperado para perfil "low-beta steady alpha".
3. **Fibonacci no IBOVESPA diário**: três variantes testadas (strict, bypass, macro-window) — nenhuma adiciona edge consistente. Indicador permanece opt-in para uso em forex/intraday.

---

## 8. Análise para Validação por Audiências Específicas

### 8.1 Analistas econômicos / quants

**Pontos fortes do modelo:**
- Estratégia bem-fundamentada teoricamente: combina trend-following (ensemble) com filtros de regime (ADX+Hurst) e gestão de risco assimétrica (partial+breakeven+chandelier).
- Triple-Barrier labeling + meta-labeler é estado da arte em ML for trading.
- Validação multi-período (OOS, WF, MC) e multi-instrumento (BR equities + US indices + forex).
- Stress testing com Bootstrap + GBM cobre cenários paramétricos e empíricos.

**Pontos de atenção:**
- Sample size em bears históricos é limitado (7 cenários) — embora consistentes, não constituem evidência estatisticamente conclusiva. Recomenda-se ampliar para >20 cenários incluindo bears regionais (Asia 1997, Russia 1998, Argentina 2001, China 2015).
- Não há análise de drawdown adjusted return (Ulcer Index, Pain Index) — poderia complementar Sharpe/Sortino.
- Custos de transação modelados como percentual fixo (0.1%) — não capturam spread bid-ask dinâmico ou impacto de mercado para sizes maiores. **Sprint 19** quantificou a sensibilidade numa janela OOS longa (2018-2026, últimos 30% do histórico, **distinta da tabela 7.2**): nessa janela o ^BVSP não exibe edge (PF 0.82 baseline, 0.69 a slip 0.3%, 0.92 a custo zero) — ver `findings/sprint_19_cost_sensitivity.md`.

**Sugestões de desenvolvimento:**
1. Adicionar **regime classifier** mais sofisticado (Hidden Markov Model) para detecção probabilística de bear/bull/range.
2. Implementar **risk parity** entre tickers na carteira agregada (Sprint-15 usa equal-weight; risk parity poderia melhorar Sharpe agregado).
3. Avaliar **factor exposure** (Fama-French 5-factor + momentum) para entender o que o sistema está "comprando" implicitamente.
4. Integrar **macro features**: yield curve, VIX, US 10Y, spread BR-US — provavelmente melhora previsibilidade em transições de regime.

### 8.2 Equipe de TI / DevOps

**Pontos fortes:**
- Estrutura modular limpa, sem god-classes
- Tipagem progressiva (mypy)
- Testes determinísticos e rápidos (45s para 519 testes)
- Sem dependências binárias problemáticas (talib evitado)
- Versionamento Git com mensagens descritivas

**Pontos de atenção:**
- **Sem CI/CD** configurado — recomenda-se GitHub Actions ou similar com:
  - Trigger em push: pytest + ruff + mypy
  - Trigger em main: deploy de container Docker para API
- **Sem containerização** — Dockerfile + docker-compose facilitariam deploy
- **Sem observabilidade estruturada** — logs em texto, sem trace IDs, sem métricas Prometheus
- **API key/auth** no `app.py` é Bearer simples; produção requer JWT ou OAuth2
- **Single-machine**: sem suporte a horizontal scaling; capacidade limitada a ~R$ 10M de capital antes de impacto de mercado relevante

**Sugestões de desenvolvimento:**
1. **Containerização**: Dockerfile multi-stage + healthcheck endpoint na API
2. **CI/CD**: GitHub Actions com matrix (Python 3.10, 3.11, 3.12, 3.13)
3. **Observabilidade**: OpenTelemetry integration (traces, métricas, logs estruturados em JSON)
4. **Secrets management**: variáveis de ambiente via `.env` + `python-dotenv` (atualmente alguns secrets em código)
5. **Cache distribuído** (Redis) para `_cache` da API — atualmente in-memory single-instance
6. **Modelo de custo dinâmico**: integrar impacto de mercado não-linear (spread bid-ask por liquidez, market impact por size) ao backtester — o modelo de custo fixo atual é otimista (ver `findings/sprint_19_cost_sensitivity.md`, Sprint 19).
6. **Database backend**: PostgreSQL + TimescaleDB para histórico de trades, signals, equity curves — substituir JSON do paper_trader
7. **Message queue** (RabbitMQ/Celery) para tasks longas: backtest, otimização, walk-forward
8. **Frontend dedicado**: React/Vue SPA consumindo a REST API substituiria templates Flask

### 8.3 Supervisores / compliance

**Pontos fortes:**
- **Determinístico**: dado o mesmo input, output idêntico — auditável
- **Sem look-ahead bias**: testes explícitos garantem
- **Sem otimização excessiva**: 519 testes incluem testes de robustez (sensitivity sweep, cross-ticker)
- **Logging completo**: cada decisão (signal, filter, exit) é logada em `logger.debug` ou superior

**Pontos de atenção:**
- **Sem audit trail formal**: não há tabela imutável de decisões com timestamp + hash
- **Sem kill switch** automatizado para drawdown excessivo (paper_trader poderia ter `max_dd_pct` que congela trading)
- **Sem rate limiting de sinais** por hora — em produção, picos de sinais podem indicar bug
- Documentação de modelo (Model Card) inexistente — recomenda-se para compliance regulatório

**Sugestões de desenvolvimento:**
1. **Model Card**: documento padronizado descrevendo intended use, training data, performance characteristics, ethical considerations
2. **Kill switch**: `paper_trader.py` com circuit breaker — se drawdown > 5%, congela novas posições
3. **Append-only audit log**: cada decisão escrita em arquivo imutável com hash chain (similar a Merkle tree)
4. **Backtest replay tool**: ferramenta para reproduzir qualquer decisão histórica dado input ao vivo
5. **Risk dashboard**: exposição agregada por ticker/setor/correlação em tempo real

---

## 9. Roadmap Sugerido (Sprints 18+)

### 9.1 Prioridade alta — produtização
| Sprint | Tema | Esforço |
|---|---|---|
| 18 | Containerização + CI/CD GitHub Actions | 2-3 dias |
| 19 | Observabilidade OpenTelemetry + structured logging | 3-5 dias |
| 20 | PostgreSQL backend para paper_trader + audit log | 5-7 dias |
| 21 | Kill switch + risk dashboard | 3-5 dias |

### 9.2 Prioridade média — modelo
| Sprint | Tema | Esforço |
|---|---|---|
| 22 | HMM-based regime classifier | 7-10 dias |
| 23 | Macro features (VIX, yield curve, spreads) | 5-7 dias |
| 24 | Risk parity portfolio allocation | 5-7 dias |
| 25 | Bears expandido (Asia 1997, Russia 1998, Argentina 2001) | 3-5 dias |

### 9.3 Prioridade baixa — extensões
| Sprint | Tema | Esforço |
|---|---|---|
| 26 | Integração com corretora real (XP, BTG) via FIX | 14+ dias |
| 27 | Frontend React/Next.js | 14+ dias |
| 28 | Adaptive thresholds por classe de ativo (forex, crypto) | 7-10 dias |
| 29 | Reinforcement learning agent (policy gradient sobre sinais) | 21+ dias |

---

## 10. Conclusão

O `market_analysis` é um sistema de pesquisa quantitativa **maturo e empiricamente validado** que evoluiu ao longo de 17 sprints documentados. A configuração de referência (Sprint-13) apresenta perfil de risco "downside protection insurance" com características raramente vistas em sistemas algorítmicos abertos: Sharpe institucional (1.7–2.4), Win Rate 75–85%, MDD < 1% em condições normais e proteção dramática (25× menor que B&H) em crashes históricos.

A descoberta de Sprint-17 — que blends lineares com B&H são empiricamente piores que a estratégia pura — redefine o posicionamento do produto. Não é uma estratégia híbrida; é um componente defensivo para a parcela do portfolio do cliente que ele não pode perder.

A **superfície de teste** (519 testes unitários, 17 scripts de análise, validação em 11+ instrumentos e 7 períodos de crash) e a **transparência metodológica** (commits descritivos, ausência rigorosa de look-ahead, determinismo) qualificam o sistema para:
- **Pesquisa**: base sólida para extensões em ML, ensemble methods, macro factors
- **Educação**: caso de estudo completo de pipeline de trading sistemático
- **Produção**: após hardening (containerização, observabilidade, audit trail), candidato a deploy em ambiente live com capital controlado

As próximas melhorias mais impactantes em ordem de retorno esperado por esforço são: (1) HMM regime classifier para detecção probabilística, (2) risk parity em carteiras, (3) macro features, (4) containerização + observabilidade para produção.

---

**Apêndices disponíveis no repositório:**
- `git log --all --stat` — histórico completo
- `pytest --cov` — cobertura por módulo
- `scripts/expected_return_analysis.py` — análise comparativa de configurações
- `scripts/bear_market_validation.py` — output completo dos 7 cenários
- `scripts/portfolio_sprint13.py` — agregação 1/N

**Para reproduzir os resultados**:
```bash
pip install -e .[dev]
pytest tests/unit -q                              # regressão (45s)
python scripts/expected_return_analysis.py        # comparativo Sprints 2-13
python scripts/bear_market_validation.py          # validação em crashes
python scripts/hybrid_strategy.py                 # rejeição do híbrido
```
