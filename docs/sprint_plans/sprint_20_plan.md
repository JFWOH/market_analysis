# Sprint 20 — Decomposição Fatorial do Alpha (Plano — Checkpoint 1, aprovado)

> **Passo 0 (disciplina S18/S19):** este plano é commitado como
> `docs/sprint_plans/sprint_20_plan.md` (`docs(planning): sprint 20 plan`) ANTES de qualquer código.
>
> **Pré-requisito:** S19 mergeado em `main` (`v0.19.0`). Branch `sprint-20-decomposicao` da main
> atualizada. **Baseline de testes (pós-S19): 549.**

## Context

O `RELATORIO_TECNICO.md` reporta Sharpe ~1.72 / PF ~2.17 (config Sprint-13, janela favorável).
O S20 pergunta com rigor estatístico: **quanto disso é alpha genuíno vs. exposição implícita a
fatores replicáveis (mercado, momentum 12-1, filtro de regime puro)?** Três regressões OLS
sucessivas (CAPM → +momentum → vs. sistema mínimo Hurst+ADX), com p-value e R², sob erros-padrão
Newey-West (HAC).

**Herança crítica do S19:** o ^BVSP **não tem edge na janela longa OOS** (PF 0.92 a custo zero,
retorno bruto −0.71% em 8 anos). Decompor uma série de retorno ~zero é degenerado. A solução
(§1) transforma o sprint num **teste de overfitting**: alpha significativo IS que **some OOS** é
a assinatura textbook de overfit — exatamente o achado que o Bloco I merece.

---

## Investigação do código existente (4 pontos)

### Ponto 1 — Janela/config: DECISÃO = (c) IS vs OOS (split 70/30) ✅

Em vez de "longa completa vs. ~7 meses do relatório" (a janela de ~7 meses é **irreproduzível** —
depende do `today` de `expected_return_analysis.py:149` — e tem **n≈145 < 500 obs**, abaixo do
mínimo da spec §5), uso o split proporcional **canônico** do projeto (`IS_RATIO=0.70`, já usado em
`expected_return_analysis.py` e no S19), decompondo os **dois lados**:

| Janela | Período ^BVSP (aprox.) | n_obs | Expectativa |
|---|---|---|---|
| **IS** (primeiros 70%) | 2000-01 → 2018-07 | ~4500 | onde a Sprint-13 foi calibrada → alpha provável (possível overfit) |
| **OOS** (últimos 30%) | 2018-07 → 2026-05 | ~1963 | janela do S19, sem edge → alpha ≈ 0 / degenerado |

**Por quê:** responde à pergunta fatorial **sem degenerar**; se o alpha é **significativo IS mas
some OOS**, é overfit comprovado por construção. Ambos os lados têm **n > 500** (poder real).
Reusa o split 70/30 (DRY). Conecta ao fio "qual janela OOS é honesta?" deferido ao Marco. A janela
de ~7 meses é citada no finding como referência, mas **não é primária** (irreproduzível, n<500).

### Ponto 2 — Config: MANTER `SPRINT13_PARAMS` (sem meta-labeler/Fibonacci), DRY com S19 ✅

O "sistema completo" (system_returns) usa `SPRINT13_PARAMS` importado de
`scripts.bear_market_validation` — **como no S19**. Esse dict **não ativa `use_meta_labeler` nem
Fibonacci**.

> **Escopo explícito do "full system" (documentar no finding):** o Modelo 3 mede
> **`ensemble + macro-lock + partial-exit + chandelier` vs. regime puro (Hurst+ADX)**.
> **Meta-labeler e Fibonacci ficam FORA deste teste.** Continuidade com o S19 vale mais que
> literalidade à spec aqui.
>
> **Pergunta aberta registrada para o Marco do Bloco I:** *"meta-labeler + Fibonacci, quando
> ativados, adicionam alpha estatisticamente significativo?"* — candidato a mini-sprint próprio.

### Ponto 3 — Threshold do Hurst no Sistema Mínimo: **0.55** ✅

Fiel à spec ("Hurst>0.55"). 0.55 = `macro_direction_hurst_min` do `SPRINT13_PARAMS`. **Não** uso
o `hurst_threshold=0.50`. ADX>25 = `adx_threshold=25.0`. Defaults parametrizados, sourced do config.

### Ponto 4 — Tickers: **só ^BVSP** no escopo principal ✅

Segue a spec (E4 = ^BVSP). **VALE3.SA fica OPCIONAL no CP3**, executado só se sobrar tempo/energia
— não compromete o sprint principal.

### Ponto 2 (técnico) — statsmodels confirmado por execução
`statsmodels 0.14.6` + `scipy 1.17.1`. `sm.OLS(y, sm.add_constant(X)).fit(cov_type='HAC',
cov_kwds={'maxlags': L})` expõe `.params/.pvalues/.rsquared/.resid/.fittedvalues/.conf_int()`.
`maxlags = int(4*(n/100)**(2/9))`. VIF via `statsmodels.stats.outliers_influence.variance_inflation_factor`.
`sklearn` **não** usado (sem p-value).

### Ponto 3 (técnico) — system_returns: fonte e alinhamento
`backtester.py`: `self.equity` (init `[capital]` @ `data.index[0]`, append por barra, l.396) +
`self.equity_dates` (l.398). →
**`system_returns = pd.Series(bt.equity, index=bt.equity_dates).pct_change().dropna()`**
(flat → retorno 0). `market_returns = market_data["Close"].pct_change()`. Alinhamento:
`pd.concat([sys, mkt], axis=1).dropna()`; `n_obs` reportado sempre.

### Ponto 4 (técnico) — reusar features, não reimplementar
`TechnicalIndicators.compute_all(data, params)` (`indicators.py:67`) devolve df com `["ADX"]` e
`["Hurst"]` (`adx_period=14`, `hurst_window=100`). Sistema Mínimo (anti-lookahead via `shift(1)`):
```python
ind   = TechnicalIndicators.compute_all(market_data, params)
sig   = ((ind["Hurst"].shift(1) > 0.55) & (ind["ADX"].shift(1) > 25)).astype(float)
returns_minimal = (sig * market_data["Close"].pct_change()).dropna()
```

### Layout flat — CONFIRMADO
`scripts/factor_decomposition.py` (script de análise). Testes importam `from
scripts.factor_decomposition import ...` (namespace). Não registra em `pyproject [py-modules]`.
PNGs gitignorados (`findings/sprint_20_data/*.png`); JSONs e CSV versionados.

---

## E1 — `scripts/factor_decomposition.py` (núcleo-biblioteca, sem rede)

Helper `_fit_ols(y, X_df, hac_maxlags=None, min_obs=30) -> dict` (add_constant, OLS+HAC,
extrai params/pvalues/r²/resid/fitted/conf_int, `n_obs`; `ValueError` se `n_obs < min_obs`).

```python
def fit_capm_local(system_returns, market_returns, risk_free_rate=0.0) -> dict:
    """R_sys - rf = alpha + beta*(R_mkt - rf) + eps (HAC).
    → alpha_annualized(%), beta, r_squared, alpha_pvalue, beta_pvalue,
      residual_std, n_obs, significant_alpha(p<0.05)."""

def fit_capm_plus_momentum(system_returns, market_returns, market_prices,
                           momentum_lookback=252, momentum_skip=21) -> dict:
    """R_sys = alpha + beta_mkt*R_mkt + beta_mom*MOM + eps.
    MOM = market_prices.pct_change(momentum_lookback-momentum_skip).shift(momentum_skip).
    Schema do M1 + beta_momentum, beta_momentum_pvalue, vif_market, vif_momentum."""

def fit_vs_minimal_system(system_returns, market_data, minimal_strategy_params=None) -> dict:
    """Sistema Mínimo (Hurst[i-1]>0.55 AND ADX[i-1]>25 else flat) via compute_all;
    R_sys = alpha + beta*R_minimal + eps.
    Schema do M1 + minimal_total_return, minimal_n_active_bars, hurst_min, adx_min."""
```
Anualização: `alpha*252*100`. Determinístico (OLS fechado; sem `random` global).

## E2 — Visualizações (matplotlib Agg, dpi=150) — por modelo
1. Scatter `system vs regressor` + reta + banda 95%. 2. Residual plot (resíduos vs fitted).
3. Q-Q plot (`scipy.stats.probplot`). → `findings/sprint_20_data/<model>_<ticker>_<window>.png`.

## E3 — Testes `tests/unit/test_factor_decomposition.py` (determinísticos, sem rede)

| # | Nome | Valida |
|---|------|--------|
| 1 ⭐ | `test_identity_alpha0_beta1_r2_1` | `system==market` → alpha≈0, beta≈1, R²≈1. **REDE DE SEGURANÇA.** |
| 2 ⭐ | `test_recovers_known_alpha` | `system = alpha_known + ruído` → recupera alpha_known. **REDE DE SEGURANÇA.** |
| 3 | `test_recovers_known_beta` | `system = beta_known*market` → recupera beta_known. |
| 4 | `test_independent_returns_low_r2` | aleatórios independentes → R²≈0, alpha não signif. |
| 5 | `test_significant_alpha_1000obs` | 1000 obs, alpha 10% anual → `alpha_pvalue<0.01`. |
| 6 | `test_nonsignificant_alpha_smallN` | 50 obs, alpha 2% → `alpha_pvalue>0.05`. |
| 7 | `test_momentum_factor_significant` | sistema segue MOM → `beta_momentum_pvalue<0.05`, sinal +. |
| 8 | `test_determinism_two_runs_identical` | duas execuções → dicts idênticos. |
| 9 | `test_too_few_obs_raises` | `n_obs<30` → `ValueError`. |
| 10 | `test_minimal_system_construction_deterministic` | params fixos → returns_minimal idêntico 2×. |
| 11 (add §2.2) | `test_minimal_signal_no_lookahead` | sinal em `df[:i]` == sinal no df completo na posição i. |

⭐ #1 e #2 são a **rede de segurança matemática** (provam a regressão correta) — atenção redobrada.
#11 é adição justificada (CLAUDE.md §2.2; MOM e sinal mínimo são cálculos temporais).
Fixtures: séries sintéticas determinísticas (`np.random.default_rng(seed)`) + OHLCV sintético
pequeno (M3). **Sem rede.** Cobertura `factor_decomposition.py` **≥85%** (rcfile temporário burla
omit `*/scripts/*`, técnica S19). CLI → `# pragma: no cover`.

## E4 — Execução real (CLI) [CP3, NÃO neste CP2]
`argparse`: `--ticker ^BVSP`, `--config sprint_13_reference`, `--windows is,oos`. Gate S18 (abortar
se `synthetic`). Por janela: backtest Sprint-13 → system_returns → 3 modelos → JSON + 3 PNGs/modelo.
Saídas `findings/sprint_20_data/`: `model{1,2,3}_<ticker>_<window>.json` (6 JSONs), `decomposition_summary.csv`
(modelo×janela), PNGs (18, ignorados). Contagem ampliada (2 janelas) documentada no finding.

## E5 — Finding `findings/sprint_20_factor_decomp.md` [CP3]
Template spec §3/E5 + coluna de janela (IS/OOS). Responde: "alpha sobrevive ao Modelo 3?" e
"sobrevive IS→OOS?". Disclosures: (a) escopo do full system = ensemble+macro+partial+chandelier,
**sem meta-labeler/Fibonacci** (+ pergunta aberta p/ Marco); (b) IS/OOS 70/30; (c) janela ~7 meses
irreproduzível/n<500; (d) HAC + VIF. **Critério 7:** se M3 alpha não-signif → cross-refs híbridos
no `RELATORIO_TECNICO.md` 8.1, **diff antes** (pergunto antes de tocar), reescrita ao Marco.

---

## Checkpoints (3)
- **CP1 — PLANO (este).** Commit `docs(planning): sprint 20 plan`. ✅
- **CP2 — NÚCLEO + TESTES.** E1 (3 modelos + `_fit_ols`), E2 (viz funcs), E3 (11 testes). Suite
  549 → **560**, zero regressão. PARA, relatório. **NÃO executa ^BVSP real.**
- **CP3 — EXECUÇÃO + FINDING.** E4 (^BVSP IS+OOS reais; VALE3 opcional), E5, decisão RELATORIO_TECNICO.
  PARA, relatório final. **Sem merge.**

## Decisões (respostas do Jeferson — todas resolvidas)
1. Janela: **(c) IS vs OOS 70/30** ✅
2. Config: **manter SPRINT13_PARAMS** (sem meta-labeler/Fibonacci); finding documenta escopo +
   pergunta aberta p/ Marco ✅
3. Hurst threshold: **0.55** ✅
4. Tickers: **só ^BVSP** principal; VALE3 opcional no CP3 ✅

## Verificação (fim do sprint)
```bash
pytest tests/unit/test_factor_decomposition.py -v      # 11 passam
pytest tests/ -q                                       # 560
python scripts/factor_decomposition.py --ticker ^BVSP --config sprint_13_reference
ls findings/sprint_20_data/    # 6 JSON + decomposition_summary.csv + 18 PNG (ignorados)
```
