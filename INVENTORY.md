# Inventário Canônico — `market_analysis`

Este arquivo documenta quais módulos são a **fonte de verdade** após a consolidação
feita em 2026-04-11. Foi escrito como parte da Fase 0 do plano de ação de refatoração.

## Arquivos canônicos (root)

| Arquivo | Responsabilidade | Destino futuro na arquitetura alvo |
|---|---|---|
| `config.py` | Configurações centrais (ASSETS, intervalos, backtest, alertas, logging) | `config/settings.yaml` (fase 1) |
| `data_provider.py` | `DataProvider`: download + normalização OHLCV, trata MultiIndex do yfinance | `src/market_analysis/data/providers.py` |
| `indicators.py` | `TechnicalIndicators`: SMA, EMA, **RSI (Wilder)**, MACD, BB, ATR, Stochastic, Volume | `src/market_analysis/indicators/technical.py` |
| `price_action.py` | `PriceActionAnalyzer`: padrões Al Brooks (pin bar, inside/outside, engulfing, reversões, failures) | `src/market_analysis/features/price_action.py` |
| `sentiment_analyzer.py` | `SentimentAnalyzer`: índice composto de sentimento (-100..+100) | `src/market_analysis/features/sentiment.py` |
| `strategy.py` | `CombinedStrategy`: unifica indicadores + price action + sentimento, gera sinais e score de tendência | `src/market_analysis/strategies/composite.py` |
| `backtester.py` | `Backtester`: motor com position sizing por risco, trailing stop, métricas por padrão | `src/market_analysis/backtest/engine.py` |
| `optimizer.py` | `StrategyOptimizer`: grid search + validação out-of-sample | `src/market_analysis/optimize/grid.py` |
| `alerts.py` | `AlertProcessor` + email SMTP com cooldown | `src/market_analysis/live/alerts.py` |
| `run.py` | Entry point com 4 modos (análise, monitoramento, backtest, otimização) | `src/market_analysis/cli.py` |
| `app.py` | Dashboard Flask + Socket.IO | `src/market_analysis/dashboard/app.py` |
| `templates/index.html` | UI do dashboard (Bootstrap + Socket.IO) | A migrar para Streamlit/Dash |
| `best_params_Ibovespa.txt` | Parâmetros otimizados do Ibovespa | `config/strategies/price_action_ibov.yaml` |
| `requirements.txt` | Dependências declaradas (mantido durante transição) | Absorvido pelo `pyproject.toml` |

## O que já foi feito (pelo refactor de 11/04)

- [x] Duplicatas movidas para `_deprecated/` (≈33 arquivos).
- [x] `DataProvider` unificado com tratamento canônico do `MultiIndex`.
- [x] **Bug crítico corrigido: RSI agora usa Wilder's SMMA** (`indicators.py:117-126`).
- [x] **Bug crítico corrigido: P&L do backtester** — agora usa `position_amount` proporcional ao `max_position_pct` e `max_risk_pct`, não o capital inteiro.
- [x] Trailing stop implementado no `Backtester`.
- [x] Métricas adicionais: `profit_factor`, `annualized_return`, `pattern_stats`.
- [x] Sistema de alertas com cooldown (evita spam de notificações duplicadas).
- [x] `run.py` unificado com 4 modos.
- [x] Logging estruturado via `logging` em todos os módulos novos.
- [x] `app.py` usa `allow_unsafe_werkzeug=True` com `cors_allowed_origins`.

## O que foi feito nesta sessão (Fase 0)

- [x] Repositório git inicializado em `main`.
- [x] `.gitignore` criado (ignora `venv/`, `__pycache__/`, `*.png`, `logs/`, `resultados*/`, etc.).
- [x] Snapshot commitado no commit inicial.
- [x] Branch `legacy/pre-refactor` criada como backup.
- [x] `INVENTORY.md` (este arquivo).
- [x] `pyproject.toml` criado.
- [x] `_deprecated/` removido (preservado em branch `legacy/pre-refactor`).

## Débito técnico ainda pendente (fases 1+)

### Crítico
- [ ] **Sharpe ratio** (`backtester.py:248`) ainda usa `√252` hard-coded, incorreto para timeframes intraday. Deve ser calculado em função do `interval` da estratégia.
- [ ] **`DASHBOARD_DEBUG = True`** (`config.py:32`) — nunca deve estar ligado em produção.
- [ ] **`yfinance` como proxy** para WIN/WDO é inadequado — considerar MT5/B3 via API real (fase 8.1).
- [ ] Ausência de **custos operacionais e slippage** no backtester — resultados ainda inflacionados.

### Estrutura
- [ ] Migrar arquivos flat para pacote `src/market_analysis/`.
- [ ] Criar `tests/` com `pytest` e fixtures determinísticas.
- [ ] Substituir cálculos manuais por `pandas-ta` (a não ser para price action customizado).
- [ ] Migrar engine própria de backtest para `vectorbt` (avaliar em fase 4).
- [ ] Configurar CI (ruff + mypy + pytest).

### Correções menores
- [ ] Vetorizar o loop `for i in range(len(dados))` em `sentiment_analyzer.py` (se ainda houver — herdado da versão original).
- [ ] Substituir `print()` remanescentes em `run.py` por `logger`.
- [ ] Validar timezones (converter para `America/Sao_Paulo` consistentemente).
- [ ] Persistir histórico de sinais em SQLite para auditoria.

## Restaurando versões antigas

```bash
git checkout legacy/pre-refactor -- <arquivo>   # traz versão antiga de um arquivo
git log --oneline legacy/pre-refactor            # histórico completo
```
