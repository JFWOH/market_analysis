# Sprint 18 — Plano de Implementação (RECONCILIADO, fonte de verdade)

> **Passo 0 (após aprovação, ANTES do núcleo):** salvar este arquivo como
> `docs/sprint_plans/sprint_18_plan.md` e commitá-lo
> (`docs(planning): sprint 18 reconciled plan`). Correção de processo: planos de
> checkpoint passam a ser arquivos versionados no repo, para sobreviver a sessões.
>
> **Escopo de execução AGORA = Checkpoint 2 (E1 + E3):** `metrics.py` + os 12
> testes. Integração no backtester, script e finding são checkpoints seguintes.
>
> **Mapa de checkpoints (operacional, conforme `prompts/PROMPTS_SPRINT_18.md`):**
> CP1 = plano (este) · CP2 = núcleo (E1 `metrics.py` + E3 testes) · CP3 = integração
> backtester + script + finding (E2 + E4 + E5). As seções 2 e 4 abaixo pertencem ao
> CP3; ficam aqui porque este doc é o plano completo do sprint.

## Context

O `RELATORIO_TECNICO.md` apresenta MDD < 1% em condições normais e razões
dramáticas (0.01×–0.05×) contra B&H em crashes. Números suspeitos por ambiguidade
de base: MDD-equity inclui caixa ocioso (fora do mercado ~70% do tempo nos
crashes), enquanto MDD-capital-at-risk mede só o capital exposto. Este sprint
desambigua: cálculo paralelo das duas métricas, testes anti-regressão, e re-emissão
dos 7 cenários de bear com as duas colunas. Primeiro sprint do Bloco I (Auditoria);
saída obrigatória é um `finding` que pode forçar reescrita do headline
("Verdade antes de feature").

## Ajustes aprovados (das suas mensagens) — incorporados

- **Ajuste 1 (CP2, teste #1):** `total_equity_mdd == capital_at_risk_mdd` só vale
  **sem caixa ocioso**. O cenário do `test_always_long_equals_both_mdds` é
  construído com `equity_curve` **idêntica** a `position_value_curve` em **todas**
  as barras (zero caixa). Só "100% em mercado" não basta.
- **Ajuste 2 (CP3):** em `test_backtester.py` só se **adicionam** funções `test_*`
  novas; as **21 funções legadas não são tocadas** (nem o runner `_TESTS`, exceto
  append). O relatório do CP3 listará quais são novas e confirmará que as legadas
  não mudaram.
- **Ajuste 3 (CP2 docstring + CP3 finding):** a curva sintética CAR só avança com
  posição aberta em **duas barras consecutivas** (`mask_open[i] & mask_open[i-1]`);
  o PnL da barra de **abertura** não entra na CAR (a barra de abertura apenas
  carrega o nível). Documentar no docstring (simétrico ao tratamento de short) e
  mencionar no finding.

---

## 1. Assinatura de `compute_drawdown_dual`

Arquivo: `metrics.py` (raiz, flat). Função pura, sem I/O, vetorizada.

```python
def compute_drawdown_dual(
    equity_curve: pd.Series,
    position_value_curve: pd.Series,
) -> dict:
    """Calcula drawdown em duas bases — total e capital-at-risk.

    Parameters
    ----------
    equity_curve : pd.Series
        Valor total da conta a cada barra (caixa livre + posições marcadas a
        mercado). Indexada por timestamp. Sem NaN.
    position_value_curve : pd.Series
        Valor absoluto das posições abertas a cada barra. **Zero quando flat.**
        Mesmo índice e comprimento de equity_curve.

    Returns (dict — 6 chaves, nomes originais):
        total_equity_mdd : float
            MDD em % positivo sobre equity_curve. 5.2 = 5.2%. Sempre >= 0.
        capital_at_risk_mdd : float
            MDD em % positivo sobre a curva sintética CAR (ver algoritmo).
            NaN se NUNCA houve posição aberta.
        time_in_market_pct : float
            % de barras com position_value > 0, em [0, 100].
        total_equity_mdd_duration_bars : int
            Barras do pico ao vale do drawdown de equity total. 0 se nenhum.
        capital_at_risk_mdd_duration_bars : int
            Idem para a curva CAR. 0 se nunca houve posição.
        mdd_explanation : str
            Texto curto (1-2 frases) explicando as duas bases, para relatórios.

    Convenção (documentar — não silenciar):
        - Flat = 0.0; máscara = position_value > 0.
        - Drawdown sempre positivo.
        - CAR avança só com posição em DUAS barras consecutivas; a barra de
          abertura carrega o nível e não gera CAR (ajuste 3).
        - Short: PnL em CAR = -1 × (price_change/entry_price), já refletido no
          position_value (módulo do nominal); short lucrativo ainda mostra recuo
          intermediário.
        - capital_at_risk_mdd = NaN só quando NUNCA operou; operou-sem-recuo → 0.0.

    Exemplo numérico (no docstring) — ajustado p/ holding de 2 barras p/ ser
    coerente com o ajuste 3 (a versão de 1 barra do plano original daria CAR=0,
    pois a barra de abertura não entra na CAR):
        Long R$ 50k; abre na barra 1, ação cai 10% na barra 2, fecha na barra 3:
        equity_curve=[100k, 100k, 90k, 90k]; position_value=[0, 50k, 50k, 0]
        total_equity_mdd = 10.0% (90k vs 100k)
        capital_at_risk_mdd = 20.0% (ret barra 2 = -10k/50k = -20%)
        # (mesma tese do exemplo original: CAR amplifica vs equity total)

    Raises
    ------
    ValueError
        Se índices das séries diferirem ou comprimentos não baterem.
    """
```

### Algoritmo CAR (capital-at-risk MDD) — MULTIPLICATIVO (decisão 6.1)

```
mask_open = position_value_curve > 0
if not mask_open.any():
    capital_at_risk_mdd = NaN ; duration = 0   # nunca operou

car_equity[0] = 1.0
for i in 1..N-1:
    if mask_open[i] and mask_open[i-1]:
        ret = (equity[i] - equity[i-1]) / position_value[i-1]
        car_equity[i] = car_equity[i-1] * (1 + ret)
    else:
        car_equity[i] = car_equity[i-1]      # flat OU barra de abertura
peak = car_equity.cummax()
dd   = car_equity/peak - 1
capital_at_risk_mdd = abs(dd.min()) * 100
```

Vetorizar com `np.where` + `np.cumprod` (sem loop Python). Durações: barras do
pico ao vale do respectivo drawdown.

### Registro

Descomentar `"metrics",  # Sprint 18` em `pyproject.toml:153`.

---

## 3. Os 12 casos de teste (`tests/unit/test_metrics.py`) — CP2/E3

Estilo de `test_backtester.py`: funções `test_*` top-level, `pd.Series`
sintéticas, determinístico (sem RNG). Nomes e identidades **originais**:

| # | Nome | O que valida |
|---|---|---|
| 1 | `test_always_long_equals_both_mdds` | **Zero caixa ocioso** (equity == position_value em TODAS as barras, ajuste 1) → `total_equity_mdd == capital_at_risk_mdd` (1e-9); `time_in_market_pct == 100`. |
| 2 | `test_never_opens_car_is_nan` | position_value sempre 0 → `total_equity_mdd == 0.0`, `capital_at_risk_mdd` é NaN, `time_in_market_pct == 0.0`. |
| 3 | `test_half_time_losing_car_doubles_total` | metade do capital exposto, em queda → CAR ≈ 2× total (tese central). |
| 4 | `test_half_time_winning_asymmetric` | 50% em mercado, ganho em janela curta → MDD CAR relativo pode exceder o de equity inteira. |
| 5 | `test_short_position_profitable_drawdown` | short lucrativo na queda → position_value = módulo; CAR captura recuo (peak crescente, MDD pequeno). |
| 6 | `test_partial_exit_position_value_halves` | partial: position_value cai 50k→25k → CAR segue contando, sem descontinuidade espúria. |
| 7 | `test_gap_overnight_handled` | salto de equity sem variação proporcional em position_value → sem NaN/inf. |
| 8 | `test_determinismo` | duas chamadas, mesmo input → dicts iguais (sem estado global). |
| 9 | `test_equity_constant_returns_zero` | equity constante → `total_equity_mdd == 0.0` e `capital_at_risk_mdd == 0.0`. |
| 10 | `test_fractional_position_value` | position_value fracionário (scale-down) → finito, sem divisão por zero. |
| 11 | `test_total_mdd_le_car_when_cash_idle` | com caixa ocioso → `total_equity_mdd <= capital_at_risk_mdd + 1e-9`. |
| 12 | `test_reference_input_reproduces_known_output` | input 5-10 barras com MDDs calculados à mão (em comentário) → reprodução exata. |

Casos 2, 7, 8, 9, 10 cobrem branches defensivos (NaN, zero-division, vazio).
**Cobertura alvo de `metrics.py` ≥ 95%.**

### Adições declaradas (além dos 12 — opcionais, só com seu OK)

- `test_no_lookahead_prefix_monotonic` — MDD total sobre prefixo `[:k]` é
  monotônico não-decrescente. **Por quê:** CLAUDE.md §2.2 pede anti-lookahead
  explícito. *(Adiciono só se você aprovar; senão fico nos 12.)*

Baseline 519 → após CP2: **531** (+ adições, se aprovadas), tudo passando.

---

## Seções 2 e 4 (CP3 — referência, NÃO implementadas agora)

- **§2 Integração no backtester:** `self.position_value = [0.0]` na init (≈linha
  103); no mark-to-market (≈367-378) append `position['amount'] + mtm` se há
  posição, senão `0.0`; em `_compute_metrics` chamar `compute_drawdown_dual` e
  adicionar campos aditivos (`max_drawdown` legado **inalterado**;
  `max_drawdown_total_equity_pct`, `max_drawdown_capital_at_risk_pct`,
  `time_in_market_pct`, `mdd_duration_total_bars`, `mdd_duration_car_bars`).
  Testes novos em `test_backtester.py` **apenas adicionados** (ajuste 2).
- **§4 Script + finding:** `scripts/rerun_bear_validation_dual_mdd.py` → CSV em
  `findings/sprint_18_data/bears_dual_mdd.csv` + PNG; `findings/sprint_18_mdd_dual.md`
  com números reais; `.gitignore` com exceção p/ o PNG; menção ao ajuste 3.

---

## Ordem de execução do Checkpoint 2 (agora)

0. **(após aprovação)** salvar este plano em `docs/sprint_plans/sprint_18_plan.md`
   + commit (`docs(planning): sprint 18 reconciled plan`).
1. Criar `metrics.py` (E1) — CAR multiplicativo, 6 chaves, flat=0, NaN-se-nunca.
2. Criar `tests/unit/test_metrics.py` (E3) — os 12 nomes acima.
3. `pytest tests/unit/test_metrics.py -v` (12/12) → `pytest tests/ -q` (531).
4. Descomentar `"metrics"` em `pyproject.toml`.
5. Commits Conventional Commits, escopo `metrics` (E1 e E3).
6. **PARAR** e produzir relatório de checkpoint (ORCHESTRATION.md): 12 passam?
   531 total? função pura/vetorizada? cobertura ≥ 95%? desvios? Não avançar ao
   CP3 sem aprovação.

## Verificação

```bash
pytest tests/unit/test_metrics.py -v
pytest tests/ -q
pytest tests/unit/test_metrics.py --cov=metrics --cov-report=term-missing   # >= 95%
ruff check metrics.py tests/unit/test_metrics.py
```

Não-regressão: total sobe exatamente +12; `backtester.py` intocado no CP2.
