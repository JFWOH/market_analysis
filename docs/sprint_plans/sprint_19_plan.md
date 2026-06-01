# Sprint 19 — Sensibilidade a Custos de Transação (Plano — Checkpoint 1)

> **Pré-requisito satisfeito:** Sprint 18 está merdado em `main` (v0.18.0). Este
> branch (`sprint-19-custos`) foi criado da main atualizada e já contém `metrics.py`
> e os campos de MDD dual no backtester — dependência dura do E1 (o sweep reporta
> `mdd_total_pct` e `mdd_capital_at_risk_pct`, que vêm do Sprint 18).
>
> **Passo 0 (lição do S18):** este plano é commitado como
> `docs/sprint_plans/sprint_19_plan.md` (`docs(planning): sprint 19 plan`) ANTES de
> qualquer código.
>
> **Baseline de testes (pós-merge S18): 535.**

## Context

O `RELATORIO_TECNICO.md` modela custos como fixos (slippage 0.1%, comissão "0.1%").
Esses valores são otimistas; spreads brasileiros dobram em stress e o impacto de
mercado cresce não-linearmente. O Sprint 19 (Bloco I — Auditoria) transforma custo
de "parâmetro fixo" em **superfície de sensibilidade**: para cada (config, ticker),
descobrir o **slippage que zera o edge** (PF → 1.0). É um sprint de findings honestos
— pode fragilizar a tese de robustez do produto, o que é esperado.

---

## Investigação do código existente (respostas às 3 perguntas)

### Q1 — backtester.py já aceita commission e slippage? Onde, nomes, defaults?

`Backtester.__init__` (backtester.py:29–66):

- **`slippage_pct`** (param, default `None` → `config.SLIPPAGE_PCT` = **0.0005** = 5 bps):
  **SIM**, é fracionário (percentual). Aplicado ao **preço** de execução em ambas as
  pernas (entrada `× (1+slip)`, saída `× (1−slip)`) em `_close_position`/`_partial_exit`
  e na abertura. **`slip_grid` mapeia direto para `slippage_pct`. Sem mudança.**
- **`commission_per_trade`** (param, default `None` → `config.COMMISSION_PER_TRADE` =
  **R$ 5.0**): existe, MAS é **custo ABSOLUTO em R$ fixo por execução** (subtraído do
  PnL), **não é percentual**. A spec §3/E1 e o template do finding tratam `comm` como
  **percentual** (0.05%–0.5%). → **mismatch semântico**. Não existe `commission_pct`.

**Conclusão Q1:** slippage está pronto; comissão-percentual **não existe**. É preciso
a "pequena modificação não-quebrante" que a própria spec §6 antecipa.

### Q2 — Como os scripts constroem strategy e rodam o Backtester? (reusar, DRY)

Padrão canônico em `scripts/bear_market_validation.py:69–83` (`_strat_metrics`):

```python
s = CombinedStrategy(ticker)
s.set_data(df.copy())
s.params.update(SPRINT13_PARAMS)
bt = Backtester(s, initial_capital=CAPITAL, cooldown_bars=2,
                commission_per_trade=0.001, slippage_pct=0.001)
m = bt.run()
```

O sweep **reusa exatamente esse padrão**, variando custo por célula. (Mesmo padrão em
`scripts/rerun_bear_validation_dual_mdd.py`.)

### Q3 — Existe config "sprint_13_reference"? Onde estão os params do Sprint-13?

**NÃO existe** registry/objeto `sprint_13_reference` no código. Os params vivem como o
dict **`SPRINT13_PARAMS`** em `scripts/bear_market_validation.py:34–43` (única fonte;
reusado pelo script de S18). O nome `sprint_13_reference` só aparece em exemplos de CLI
e sprints futuros (S21/S25 mencionam `configs/presets/sprint_13_reference.yaml`, que
**ainda não existe**).

**Conclusão Q3 (DRY):** `cost_sensitivity.py` reusa `SPRINT13_PARAMS` importado de
`scripts.bear_market_validation`, com um mapa `CONFIGS = {"sprint_13_reference":
SPRINT13_PARAMS}`. Formalizar um registry YAML fica para S21+ (fora de escopo).

### Layout flat — CONFIRMADO

`cost_sensitivity.py` vai em **`scripts/`** (é script de análise como
`bear_market_validation.py`), **não na raiz**. Importável nos testes via
`from scripts.cost_sensitivity import ...` (namespace package — `scripts/` não tem
`__init__.py`, mas resolve com a raiz no `sys.path`, padrão já usado). **Não** registra
em `pyproject [tool.setuptools] py-modules` (scripts não são módulos top-level).

---

## E1a — Mudança não-quebrante no backtester (habilita o eixo comissão %)

**Decisão recomendada (Path A):** adicionar `commission_pct` ao `Backtester`.

- Assinatura: `commission_pct: float | None = None` em `__init__`
  → `getattr(config, "COMMISSION_PCT", 0.0)` (default **0.0** → opt-in, CLAUDE.md §2.3).
- Aplicação como custo fracionário sobre o **nocional**, em 3 pontos (espelhando
  `commission_per_trade`):
  - abertura: `capital -= ... + self.commission_pct * pos_amount`
  - `_close_position`: `pnl -= self.commission_pct * position['amount']` (+ no campo `commission`)
  - `_partial_exit`: `pnl -= self.commission_pct * closed_amount`
- **Não-quebrante:** default 0.0 → todos os termos somem; os 535 testes ficam idênticos.
- Justificativa vs alternativas: (B) reusar `commission_per_trade` absoluto torna o eixo
  comissão sem sentido (valores 0.0005–0.005 = R$ centavos); (C) dobrar comissão dentro
  do slippage torna os eixos redundantes (heatmap degenerado na diagonal). Path A é a
  única que honra a semântica percentual da spec mantendo o custo absoluto disponível.
- **Distinção comm vs slip preservada:** slippage move o *preço* (e afeta o sizing via
  `entry_price`); `commission_pct` é dedução fracionária do PnL (não afeta sizing). Logo
  os dois eixos do heatmap não são redundantes.

**Testes (E1a) — ADITIVOS em `tests/unit/test_backtester.py` (não tocar nas 24 funções
existentes; append no runner `_TESTS`):**
- `test_commission_pct_default_zero_unchanged` — com default (0.0), métricas idênticas a
  uma corrida sem o parâmetro (regressão).
- `test_commission_pct_reduces_pnl` — `commission_pct>0` reduz `final_capital` vs 0.

---

## E1 — `cost_sensitivity_sweep` (scripts/cost_sensitivity.py)

Assinatura **exata da spec** (com a interpretação comm→`commission_pct`):

```python
def cost_sensitivity_sweep(
    strategy_config: dict,
    data: pd.DataFrame,
    comm_grid: list[float] | None = None,   # default [0.0005,0.001,0.002,0.005]
    slip_grid: list[float] | None = None,   # default [0.0005,0.001,0.002,0.003,0.005]
    initial_capital: float = 100_000,
    risk_per_trade: float = 0.01,
    strategy_factory=None,                   # SEAM de teste (ver Dúvida 2)
) -> pd.DataFrame:
    """Roda um backtest por célula (comm × slip).

    Colunas (shape = len(comm_grid)*len(slip_grid) × 9):
        comm, slip, pf, sharpe, win_rate, num_trades,
        total_return_pct, mdd_total_pct, mdd_capital_at_risk_pct

    comm → commission_pct ; slip → slippage_pct ; commission_per_trade FIXADO em 0.0
    para isolar os eixos percentuais. risk_per_trade entra via params (max_risk_pct).
    Nota: custos modelados aqui não capturam impacto de mercado para sizes grandes.
    """
```

- Por célula reusa o padrão Q2; `mdd_total_pct`/`mdd_capital_at_risk_pct` vêm de
  `max_drawdown_total_equity_pct` / `max_drawdown_capital_at_risk_pct` (S18).
- Paralelização opcional via `multiprocessing.Pool` (guard `__main__` no script).

## E2 — `find_breakeven_slippage`

Assinatura exata da spec:

```python
def find_breakeven_slippage(
    strategy_config: dict,
    data: pd.DataFrame,
    commission: float = 0.001,
    slip_search_range: tuple = (0.0001, 0.01),
    metric: str = "profit_factor",
    target_value: float = 1.0,
    tolerance: float = 0.01,
    strategy_factory=None,
) -> dict:
    """Busca binária do slippage onde `metric` = `target_value`.
    Retorna: breakeven_slippage (NaN se já abaixo do target no slip mínimo),
             metric_at_breakeven, num_iterations, converged.
    """
```

- Pressupõe **monotonia** de PF↓ com slip↑ (validada pelo teste E4#3).
- Borda: se em `slip_search_range[0]` a métrica já < target → `breakeven_slippage = NaN`.

## E3 — Visualizações (matplotlib Agg, dpi=150)

1. **Heatmap PF** — `imshow`, `cmap="RdYlGn"`, eixo X=slip, Y=comm, labels nas células.
   → `findings/sprint_19_data/heatmap_<config>_<ticker>_pf.png`
2. **Heatmap Sharpe** — idem, escala de cor fixa **[-2, 3]** (comparabilidade).
   → `heatmap_<config>_<ticker>_sharpe.png`
3. **Curva de degradação** — slip no X; PF/Sharpe/WinRate no Y; linha horizontal em
   `y=1.0`; marca vertical no breakeven slip. → `degradation_<ticker>.png`

## E4 — 8 testes (`tests/unit/test_cost_sensitivity.py`, determinísticos, sem rede)

| # | Nome | Valida |
|---|------|--------|
| 1 | `test_losing_strategy_breakeven_nan` | estratégia perdedora → `breakeven_slippage` é NaN |
| 2 | `test_robust_strategy_high_breakeven` | edge sintético enorme → `breakeven_slippage > 0.005` |
| 3 | `test_pf_monotonic_decreasing_in_slippage` | comm fixa: PF decresce monotonicamente com slip |
| 4 | `test_idempotent_same_seed` | duas corridas, mesma seed → resultado idêntico |
| 5 | `test_sweep_returns_correct_shape` | DataFrame shape = (len(comm)*len(slip), 9) e colunas certas |
| 6 | `test_defaults_used_when_grids_none` | grids None → usa os defaults da spec |
| 7 | `test_zero_cost_is_best` | PF com slip=0,comm=0 é o maior do grid |
| 8 | `test_breakeven_converges_under_30_iter` | busca binária converge em < 30 iterações |

- **Sem rede**: os testes usam dados sintéticos determinísticos + `strategy_factory`
  injetando uma estratégia mock com sinais controlados (ver Dúvida 2). Casos 1 e 2
  exigem P&L controlado, impossível com `CombinedStrategy` sobre série arbitrária.
- **Anti-lookahead (CLAUDE.md §2.2):** o sweep é um *wrapper* de backtests — não introduz
  cálculo temporal novo; a garantia anti-lookahead é herdada do motor (já coberta). Sem
  teste anti-lookahead novo aqui (justificado).

## E5 — Execução real (`scripts/cost_sensitivity.py` CLI)

- `argparse`: `--ticker`, `--config` (default `sprint_13_reference`), `--all-tickers`,
  `--n-jobs`. Guard `if __name__ == "__main__":` (multiprocessing no Windows).
- Tickers: `^BVSP`, `VALE3.SA`, `PETR4.SA`. Janela **OOS = último 30% do histórico**
  por ticker (ver Dúvida 3).
- **Lição do S18:** checar conectividade yfinance e **recusar dado sintético disfarçado
  de real** (abortar/avisar se `source=="synthetic"`).
- Saídas em `findings/sprint_19_data/`: `sweep_bvsp.csv`, `sweep_vale3.csv`,
  `sweep_petr4.csv`; 9 PNGs (3×3); `breakeven_summary.csv` (3 linhas).
- `.gitignore`: PNGs já cobertos por `*.png` global; adicionar linha explícita
  `findings/sprint_19_data/*.png` (precedente S18). CSVs versionados.

## E6 — Finding (`findings/sprint_19_cost_sensitivity.md`)

- Preenche o template `market_analysis_package/findings/sprint_19_cost_sensitivity.md`
  com números reais. Responde explicitamente, por ticker: "sobrevive a slippage 0.3%?".
- **Critério 7 da spec:** se `^BVSP` **não** passa @ slip 0.3% → TL;DR em letras grandes
  + atualização do `RELATORIO_TECNICO.md`. **Aplicar a lição híbrida do S18:** correção
  mínima (cross-ref nas seções 5.7.1/7/8.1/8.2) agora; reescrita profunda do
  posicionamento **deferida ao Marco do Bloco I** (pós-S22). Ver Dúvida 7.

---

## Divisão em checkpoints (confirmando a sua sugestão de 3)

- **CP1 — PLANO (este).** Commit `docs(planning): sprint 19 plan`. Aguarda aprovação.
- **CP2 — NÚCLEO + TESTES.** E1a (backtester `commission_pct` + 2 testes aditivos),
  E1 (sweep), E2 (breakeven), E3 (funções de viz), E4 (8 testes). Rodar suite completa
  (zero regressão sobre 535; backtester.py é o ponto sensível — disciplina aditiva).
  Alvo: 535 → **545**. PARA, relatório.
- **CP3 — EXECUÇÃO + FINDING.** E5 (script + 3 tickers, dados reais), E6 (finding com
  números reais), `.gitignore`, decisão do `RELATORIO_TECNICO.md`. PARA, relatório final.

---

## Dúvidas que precisam do seu input

1. **Comissão % no backtester (Path A):** confirmo adicionar `commission_pct`
   (fracionário, default 0.0, não-quebrante)? É a base de todo o eixo "comissão" do
   sweep. *(Recomendo sim.)*
2. **Seam de teste:** aceito estender a assinatura com `strategy_factory=None` opcional
   (default = padrão `CombinedStrategy`) para injetar uma estratégia mock determinística
   nos testes (casos 1 e 2 exigem P&L controlado)? *(Recomendo sim; é a forma limpa de
   testar sem rede e sem depender do comportamento da CombinedStrategy em série sintética.)*
3. **Janela OOS:** último 30% do histórico por ticker (recomendado, sem datas fixas) ou
   datas fixas 2024–2026 como sugere a spec?
4. **Fonte do `sprint_13_reference`:** reusar `SPRINT13_PARAMS` de
   `scripts.bear_market_validation` (DRY) — confirmo? Ou criar já um módulo/registry de
   config? *(Recomendo reusar; registry YAML fica para S21+.)*
5. **Comissão absoluta nos sweeps:** fixar `commission_per_trade=0.0` nas corridas do
   sweep para isolar os eixos percentuais (senão o R$ 5.0 default contamina)? *(Recomendo sim.)*
6. **Cobertura de `scripts/`:** o `pyproject` omite `*/scripts/*` da cobertura. Para
   provar ≥ 90% em `cost_sensitivity.py`, medir explicitamente (invocação dedicada que
   não aplica o omit). Confirmo essa abordagem?
7. **RELATORIO_TECNICO.md (se ^BVSP falhar @0.3%):** aplicar a via híbrida do S18
   (cross-ref factual agora + reescrita profunda deferida ao Marco do Bloco I)? *(Recomendo sim.)*

---

## Verificação (ao fim do sprint)

```bash
pytest tests/unit/test_cost_sensitivity.py -v        # 8 passam
pytest tests/ -q                                     # 545 (535 + 8 + 2)
pytest --cov=scripts.cost_sensitivity --cov-report=term-missing tests/unit/test_cost_sensitivity.py  # >= 90%
python scripts/cost_sensitivity.py --ticker ^BVSP --config sprint_13_reference
python scripts/cost_sensitivity.py --all-tickers
ls findings/sprint_19_data/        # 3 CSV + 9 PNG + breakeven_summary.csv
```

Critérios de aceitação (spec §4): suite passa; cobertura ≥ 90%; 3 CSVs; 9 PNGs;
`breakeven_summary.csv` com 3 linhas; finding responde "sobrevive a slip 0.3%?" por
ticker; se ^BVSP falha @0.3%, TL;DR grande + atualização do RELATORIO_TECNICO.md.
