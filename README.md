# market_analysis

Sistema de análise quantitativa, backtesting, geração de sinais e execução simulada (paper trading) para mercados financeiros, com foco no mercado brasileiro (B3) e generalização demonstrada para índices internacionais e forex.

Desenvolvido em Python, modularizado em ~19 mil linhas de código produtivo, com **519 testes unitários** e 17 sprints de evolução documentados. Layout flat (módulos top-level na raiz). Sem dependências binárias problemáticas (TA-Lib evitado para garantir reprodutibilidade).

---

## Documentação

| Documento | Propósito |
|---|---|
| **`RELATORIO_TECNICO.md`** | Relatório técnico completo: arquitetura, metodologia, resultados empíricos, limitações conhecidas. Comece por aqui para entender o sistema. |
| **`CLAUDE.md`** | Convenções inegociáveis de desenvolvimento (testes obrigatórios, anti-look-ahead, opt-in features, layout flat). Leitura obrigatória antes de programar. |
| **`MANUAL_USUARIO.md`** | Manual de uso do sistema. |
| **`GUIA_DE_USO.md`** | Guia rápido de uso. |
| **`market_analysis_package/`** | Plano de evolução dos Sprints 18-33 (auditoria → hardening → interface gráfica). Especificação executável para o ciclo atual de desenvolvimento. |

---

## Instalação

Requer Python 3.10+ (validado em 3.13). Recomenda-se ambiente virtual dedicado.

```bash
# Criar e ativar venv (Windows)
python -m venv venv
venv\Scripts\activate

# Instalar em modo editável com dependências de desenvolvimento
pip install -e ".[dev]"
```

Grupos opcionais de dependências disponíveis: `gui`, `api`, `ml`, `stats`, `optim`, `dev`, `docs`. Instale conforme a necessidade (ex.: `pip install -e ".[ml,stats]"`).

> **Versões fixadas**: `pandas>=2.0,<3.0` e `yfinance>=0.2.40,<1.0`. Os tetos protegem contra breaking changes de major versions não validadas. Modernização é decisão consciente, não automática.

---

## Rodar os testes

```bash
pytest tests/ -q                       # suite completa (519 testes, ~45s)
pytest tests/unit/test_strategy.py -v  # arquivo específico, verboso
pytest --cov=. --cov-report=html       # com cobertura
```

Regra do projeto: **nenhum código novo entra sem teste correspondente**, e a suite completa precisa passar antes de qualquer commit.

---

## Estrutura

Layout flat — módulos Python vivem na raiz, não dentro de uma pasta de pacote.

```
market_analysis/
├── strategy.py          # Estratégia combinada (geradores + filtros)
├── indicators.py        # Indicadores técnicos + Fibonacci
├── backtester.py        # Motor de simulação event-driven
├── meta_labeler.py      # Pipeline ML (Triple-Barrier + RandomForest)
├── optimizer.py         # Grid search + Walk-Forward + DSR
├── paper_trader.py      # Engine de trading simulado
├── stress_test.py       # Monte Carlo (Bootstrap + GBM+Jump)
├── price_action.py      # Detecção de padrões
├── data_provider.py     # Adaptador yfinance
├── api.py / app.py      # REST API + Dashboard web
├── ...                  # demais módulos do motor
├── tests/unit/          # 519 testes
├── scripts/             # análises e validações
└── market_analysis_package/  # plano dos Sprints 18-33
```

Detalhamento completo da arquitetura em camadas: ver `RELATORIO_TECNICO.md` seção 2.

---

## Princípios de design

- **Determinismo**: dado o mesmo input, output idêntico. Sem `random.seed()` global; RNG explícito por simulação.
- **Ausência de look-ahead bias**: garantida por janelas exclusivas e testes específicos anti-lookahead.
- **Opt-in features**: novas capacidades entram com flag desligado por padrão, preservando retrocompatibilidade.
- **Test-first**: regressão obrigatória de 100% antes de cada commit.

---

## Status

**Versão**: 0.18.0-dev — início do programa de Sprints 18-33.

O ciclo atual de desenvolvimento começa com uma fase de **auditoria honesta** (Bloco I) que reavalia as propriedades estatísticas do sistema antes de qualquer nova feature. Ver `market_analysis_package/sprints/ROADMAP.md` para o plano completo e `market_analysis_package/findings/MARCO_BLOCO_I.md` para o gate de decisão estratégica.

---

*Sistema de pesquisa quantitativa. Não constitui recomendação de investimento. Paper trading apenas — sem integração com corretora real.*
