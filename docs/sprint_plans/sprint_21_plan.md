# Sprint 21 — Walk-Forward com Re-otimização Honesta (Plano — Checkpoint 1)

> **Passo 0 (disciplina S18/S19/S20):** este plano é commitado como
> `docs/sprint_plans/sprint_21_plan.md` (`docs(planning): sprint 21 plan`) ANTES de qualquer código.
>
> **Pré-requisito:** S20 mergeado em `main` (`v0.20.0`). Branch `sprint-21-walkforward` da main
> atualizada. **Baseline de testes (pós-S20): 561.**

## Context

`walk_forward_real.py`/`walk_forward_sprintN.py` e o `optimizer.py` já fazem walk-forward, mas
nenhum entrega a medida que o S21 quer: **degradação IS→OOS sob re-otimização honesta, com janelas
anchored bar-based, embargo, e seleção deflada por DSR**. O S21 reescreve o WF para re-otimizar
*dentro de cada janela IS* e aplicar os params daquela janela no OOS seguinte — a degradação
observada é a estimativa não-enviesada de overfitting de seleção de hiperparâmetros. Fecha o
argumento de S19 (sem edge OOS em ^BVSP) e S20 (sem alpha): se a degradação for severa, o "Sharpe
1.72" reportado é majoritariamente data dredging.

---

## INVESTIGAÇÃO DO CÓDIGO (respostas factuais às 3 perguntas)

### 1. DSR JÁ EXISTE — sim, reutilizável. NÃO reimplementar. ✅

- **Onde:** `Backtester.deflated_sharpe_ratio(...)` (`backtester.py:597`), **`@staticmethod`** (a
  `optimizer.py:172` chama `Backtester.deflated_sharpe_ratio(...)` sem instância).
- **Assinatura exata:**
  ```python
  Backtester.deflated_sharpe_ratio(
      sharpe_obs: float,      # Sharpe POR-PERÍODO (não anualizado)
      n_obs: int,             # nº de retornos
      n_trials: int,          # nº de configurações testadas (deflação)
      skew: float = 0.0,      # skewness dos retornos
      kurt: float = 3.0,      # kurtosis NÃO-excesso (normal=3.0)
      sharpe_variance: float | None = None,
  ) -> float                  # probabilidade DSR ∈ [0,1] (Φ(t_ratio); ≥0.95 = confiança)
  ```
- **Inputs já vêm prontos no dict de métricas do backtester** (`backtester.py:884-888`):
  `sharpe_per_period`, `n_return_obs`, `return_skew`, `return_kurt` (kurt já convertido p/
  não-excesso na l.814). Também há `sharpe_ratio` (anualizado).
- **Reuso como `metric_to_optimize='sharpe_dsr'`:** sim. Para cada candidato no fold, rodo o
  backtest → pego os 4 campos acima → `dsr = Backtester.deflated_sharpe_ratio(sharpe_per_period,
  n_return_obs, n_trials=<nº de configs do fold>, skew, kurt)`. Seleciono `argmax(dsr)`. É
  exatamente o que `optimizer.optimize()` já faz (l.167-178) — só **reaproveito a função**, não a
  CLI. `metric_to_optimize='sharpe'` (raw, via `sharpe_ratio`) fica como opção.
- **O que falta:** nada no cálculo do DSR. A única "lacuna" é que `optimizer._VALID_METRICS` **não
  inclui** `dsr`/`sharpe_dsr` para ordenação — mas eu não uso o `optimize()` wrapper; faço a seleção
  no `walkforward_honest` ordenando pelo campo `dsr`. Sem mudança em `optimizer.py`.

### 2. IMPLEMENTAÇÃO ANTIGA (para o E5) — nenhum script legado serve como referência limpa. ⚠️

Investiguei os três candidatos:

| Script | Re-otimiza? | Janelas | Dados | Reprodutível p/ E5? |
|---|---|---|---|---|
| `scripts/walk_forward_real.py` | **SIM, por fold** (grid IS→OOS, l.135-150) | non-anchored, fold-local 70/30, **sem embargo** | reais (^BVSP/USDBRL), **datas fixas 2023-24**, grid Sprint-1 (8 combos) | ❌ não casa janelas/grid |
| `scripts/walk_forward_sprint1.py` | sim, por fold | non-anchored 70/30 | **sintéticos** (seed fixo) | ❌ sintético |
| `scripts/walk_forward_sprint4.py` | sim (marco histórico) | non-anchored | sintético/histórico | ❌ não casa |

**Achado factual (corrige a premissa da spec §1):** `walk_forward_real.py` **NÃO usa "params
fixos"** — ele re-otimiza por fold com um grid minúsculo (Sprint-1), non-anchored, sem embargo,
selecionando por `sharpe_ratio` cru. Logo **nenhum** dos legados é o "antigo de params fixos" da
spec, **nem** roda no mesmo dataset/param_space que o honesto exigiria.

**Decisão para o E5 (a única forma de comparar "mesmo dataset/param_space"):** reconstruir o método
"antigo/fixo" *dentro* de `compare_walkforward_methods.py`, reusando a mesma maquinaria do
`walkforward_honest`. O "antigo fiel à spec" = **otimiza UMA vez no histórico inteiro → fixa os
params → aplica nas mesmas janelas OOS rolantes** (params "viram" todo o histórico = data dredging).
O "honesto" = re-otimiza por fold IS. A diferença OOS entre os dois é a estimativa de data dredging.
Os scripts legados são citados no finding como contexto histórico, não como referência executável.

### 3. INFRAESTRUTURA DE OTIMIZAÇÃO — grid e Optuna existem; reuso o avaliador, não o wrapper. ✅

- **Grid search:** `StrategyOptimizer.optimize()` (`optimizer.py:86`) — `itertools.product` sobre
  `param_grid: dict[str,list]`, filtros de qualidade, DSR por resultado, paralelismo
  `ThreadPoolExecutor`. **Mas** carrega dados por datas via `_load_data`→`load_historical` (rede).
  Não serve para otimizar uma **janela in-memory**.
- **Avaliador DRY (o que vou reusar):** `optimizer._eval_combo(ticker, name, params, data, capital)`
  (`optimizer.py:21`) — **módulo-level, picklable**, recebe um DataFrame in-memory:
  `CombinedStrategy(ticker,name,params) → set_data(data) → Backtester(...).run()`. É a unidade de
  avaliação (params × janela) que o `walkforward_honest` vai chamar. **Como S19/S20 reusaram
  `bear_market_validation`, reuso `_eval_combo`** (mais `Backtester.deflated_sharpe_ratio`).
- **Optuna:** `optuna 4.8.0` **importa** (confirmado por execução). Existe `scripts/optimize_optuna.py`
  como **referência de padrão** (`TPESampler(seed=42)`, `study.optimize`, `suggest_*`), mas é
  standalone (faz PurgedKFold + meta-labeler dentro do objective, maximiza PF, baixa seus próprios
  dados) — **não reutilizável direto**, apenas o padrão de sampler/seed. O objective do
  `walkforward_honest` vai usar `suggest_categorical` sobre o `param_space` discreto + `_eval_combo`.
- **`Backtester` por combinação:** invocado exatamente via `_eval_combo` (acima).

### Layout & registro — CONFIRMADO

- `walkforward_honest.py` na **RAIZ** (módulo top-level; roda `python -m walkforward_honest`, spec §7).
- `compare_walkforward_methods.py` em **`scripts/`**.
- **Descomentar** `pyproject.toml:157` `# "walkforward_honest",    # Sprint 21` → `"walkforward_honest",`.
- Testes importam `import walkforward_honest` (raiz). PNGs gitignored (`findings/sprint_21_data/*.png`);
  JSONs + CSV versionados.

---

## DECISÕES INCORPORADAS (não re-perguntar)

- **Janelas:** IS 504 barras, OOS 252, embargo 20, **anchored** (is_start fixo; IS expande).
- **Otimizador:** **Optuna** default (`n_trials=100`), `TPESampler(seed=...)`. Grid disponível p/
  espaços pequenos/testes.
- **param_space:** regime + saída, 5-6 params — **proposta abaixo para aprovação**.

---

## PROPOSTA DE param_space (5-6 params) — para o Jeferson aprovar

**Base fixa** (continuidade S19/S20 — "full system" = `SPRINT13_PARAMS` SEM meta-labeler/Fibonacci):
`use_regime_filter=True, use_vol_targeting=True, use_ensemble=True, macro_direction_lock=True,
use_partial_exit=True, use_chandelier_after_be=True` (os defaults do SPRINT13). Sobre essa base,
otimizo **6 knobs** (3 de regime/entrada, 3 de saída/risco) — discretos (dict[str,list], casa com a
assinatura E1 e torna o Jaccard de estabilidade bem-definido):

| # | Param | Grupo | Valores propostos | Default S13 | Justificativa do range |
|---|---|---|---|---|---|
| 1 | `adx_threshold` | regime | `[20.0, 25.0, 30.0]` | 25.0 | força mínima de tendência; abaixo de 20 vira ruído, acima de 30 quase não opera (B3). |
| 2 | `hurst_threshold` | regime | `[0.50, 0.55, 0.60]` | 0.50 | persistência; 0.50=random walk (piso), 0.60=exigência forte. Cobre o `macro_hurst_min` 0.55. |
| 3 | `macro_direction_ret_min` | regime | `[0.05, 0.08, 0.12]` | 0.05 | gatilho do macro-lock; 5–12% acumulado define "tendência macro confirmada". |
| 4 | `atr_stop_multiplier` | saída | `[1.0, 1.5, 2.0]` | 1.5 | largura do stop; espelha o range testado em `optimize_optuna` (1–3) discretizado. |
| 5 | `atr_target_multiplier` | saída | `[2.0, 3.0, 4.0]` | 3.0 | alvo; razão alvo/stop de ~2:1 a 4:1. |
| 6 | `chandelier_atr_mult` | saída | `[2.0, 3.0, 4.0]` | 3.0 | trailing pós-breakeven; RELATORIO §5.5.2 cita sweep [1.5..4.0]. |

**Tamanho do grid:** 3⁶ = **729 combos**. Justifica a escolha do **Optuna** como default (729×5
folds×3 tickers = 10 935 backtests no grid completo — inviável; Optuna `n_trials=100` corta para
~1 500). Para **grid mode** (testes/espaços pequenos) uso um subgrid 2×2×... ≤ ~16 combos.

**Por que estes 6** (e não outros): são os knobs de maior alavancagem de um sistema regime+saída e os
que a própria base do projeto discute tunar (ADX/Hurst no filtro; chandelier no §5.5.2; atr_stop/target
no `optimize_optuna`). Excluo deliberadamente meta-labeler/Fibonacci (continuidade S19/S20 + custo de
treino por trial) e sizing/Kelly (ortogonal à pergunta de overfitting de regime/saída).

> **Variante de fallback se 729 for julgado grande demais mesmo p/ Optuna:** cair para **5 params**
> (remover #3 `macro_direction_ret_min`) → 3⁵=243. Decido manter 6 e confiar no Optuna; **peço
> aprovação**.

---

## E1 — `walkforward_honest.py` (RAIZ)

```python
@dataclass
class WalkForwardFold:
    fold_id: int
    is_start: pd.Timestamp; is_end: pd.Timestamp
    oos_start: pd.Timestamp; oos_end: pd.Timestamp
    best_params: dict
    is_metrics: dict; oos_metrics: dict
    top_k_params: list[dict]          # EXTENSÃO justificada: top-K do fold (p/ Jaccard E3)

@dataclass
class WalkForwardResult:
    folds: list[WalkForwardFold]
    is_sharpe_mean: float; oos_sharpe_mean: float
    is_pf_mean: float; oos_pf_mean: float
    degradation_pct: float
    param_stability_score: float
    def to_dataframe(self) -> pd.DataFrame: ...   # 1 linha/fold
    def to_dict(self) -> dict: ...                # serializável p/ JSON

def generate_folds(
    n_bars: int, n_folds: int, is_window_bars: int, oos_window_bars: int,
    embargo_bars: int, anchored: bool = True,
) -> list[tuple[int, int, int, int]]:
    """Posições inteiras (is_start, is_end, oos_start, oos_end) por fold.
    anchored: is_start=0; is_end = is_window + k*oos_window; oos_start = is_end+embargo.
    sliding:  is_start = k*oos_window; is_end = is_start+is_window; oos_start = is_end+embargo.
    ValueError se n_bars insuficiente para n_folds (oos_end do último fold > n_bars)."""

def optimize_window(
    data: pd.DataFrame, ticker: str, param_space: dict[str, list],
    optimizer: str = "optuna", n_trials_optuna: int = 100,
    metric_to_optimize: str = "sharpe_dsr", seed: int = 42,
    min_trades: int = 3, top_k: int = 3, n_jobs: int = 1,
) -> tuple[dict, dict, list[dict]]:
    """Otimiza UMA janela IS (in-memory) reusando _eval_combo + deflated_sharpe_ratio.
    grid: itertools.product sobre param_space. optuna: suggest_categorical sobre as listas,
    TPESampler(seed). Métrica 'sharpe_dsr' => argmax DSR (n_trials = nº configs avaliadas);
    'sharpe' => argmax sharpe_ratio. Returns (best_params, best_is_metrics, top_k_params)."""

def walk_forward_with_reopt(
    data: pd.DataFrame, param_space: dict[str, list],
    ticker: str = "^BVSP", n_folds: int = 5,
    is_window_bars: int = 252*2, oos_window_bars: int = 252, embargo_bars: int = 20,
    anchored: bool = True, optimizer: str = "optuna", n_trials_optuna: int = 100,
    metric_to_optimize: str = "sharpe_dsr", base_params: dict | None = None,
    seed: int = 42, n_jobs: int = 1,
) -> WalkForwardResult:
    """Anchored WF com re-otim por fold. Para cada fold: optimize_window(IS) →
    aplica best_params no OOS (_eval_combo) → registra is/oos metrics. base_params =
    SPRINT13 base (knobs sobrescritos pelo param_space). Log ≤5 linhas/fold."""
```

**Anti-lookahead:** garantido por construção (IS estritamente antes de OOS, com `embargo_bars` de gap)
— mais o teste E4 #3. **Determinismo:** `TPESampler(seed)`, `n_jobs=1` default (CLAUDE.md §2.6).

## E2 — `compute_degradation(is_metric, oos_metric, metric_type="sharpe") -> dict`
`absolute_degradation = oos-is`; `relative_degradation_pct = (oos-is)/is*100` (guarda div/0 e sinal de
`is`); `is_significant` (bool, limiar |rel|>20%); `interpretation` ∈ {robusto<20% / moderado 20-50% /
severo 50-80% / artefato>80%} (limiares da spec §3/E2; degradação = piora, sinal negativo).

## E3 — `param_stability_score(folds, top_k=3) -> float`
Para cada par de folds **consecutivos**, Jaccard entre os conjuntos top-K (cada param set = `frozenset`
de itens `(nome, valor)`; combos discretos → interseção/união bem-definidas). Retorna a média.
1.0 = top-K idêntico entre folds (estável); 0.0 = disjunto (overfitting). Usa `fold.top_k_params`.

## E4 — `tests/unit/test_walkforward_honest.py` (determinísticos, sem rede) — 10 casos

1. `test_ar1_meanreverting_low_degradation` — série AR(1) mean-reverting → params ótimos recuperados, degradação ≈ 0.
2. `test_pure_random_high_degradation` — série aleatória pura → alta degradação (overfitting esperado).
3. `test_embargo_respected` — nenhuma data OOS cai dentro de [is_start, is_end+embargo] em qualquer fold.
4. `test_anchored_keeps_is_start_fixed` — `anchored=True` mantém `is_start` constante; sliding o move.
5. `test_small_grid_exhaustive` — grid de 4 combos é varrido exaustivamente (grid mode).
6. `test_determinism_same_seed` — mesma seed → `WalkForwardResult` idêntico (folds, métricas, score).
7. `test_insufficient_data_raises` — dados < necessário para `n_folds` → `ValueError`.
8. `test_stability_score_1_when_same_best` — todos os folds com mesmo top-K → score = 1.0.
9. `test_stability_score_0_when_disjoint` — folds com top-K disjuntos → score = 0.0.
10. `test_dsr_penalizes_many_trials` — grid grande com diferença real ínfima → DSR do "melhor" < Sharpe cru (deflação atua).

Extra (cobertura, não conta como E4): `test_compute_degradation_interpretations` (mapeia 4 faixas) e
smoke de `to_dataframe/to_dict`. **Fixtures:** séries sintéticas com `np.random.default_rng(seed)` +
OHLCV pequeno; **sem rede**. Cobertura `walkforward_honest.py` **≥85%** (CLI/`__main__` e camada de
execução real sob `# pragma: no cover`, técnica S19/S20). DSR é testado indiretamente (#10) + já tem
`test_optimizer.py`.

## E5 — `scripts/compare_walkforward_methods.py` (antigo vs honesto, mesmo dataset/param_space)
- **Honesto:** `walk_forward_with_reopt(...)` (re-otim por fold).
- **Antigo/fixo (reconstruído):** `optimize_window(histórico inteiro)` → `best_global` → aplica
  `best_global` **fixo** nas MESMAS janelas OOS (sem reopt por fold). IS metric = otimização global.
- Tabela comparativa (spec §3/E5): `| Método | IS Sharpe mean | OOS Sharpe mean | Degradação |`.
- A diferença de OOS Sharpe (honesto − fixo) = **estimativa do data dredging**. Saída:
  `findings/sprint_21_data/walkforward_comparison.csv`. Gate S18 (abortar se `synthetic`).

## E6 — Execução completa (3 tickers, dados reais)
`^BVSP` (5 folds), `^GSPC` (5 folds), `VALE3.SA` (4 folds). Saídas `findings/sprint_21_data/`:
3 JSONs (`walkforward_{slug}.json` via `to_dict`), 3 PNGs (IS-vs-OOS Sharpe por fold, gitignored),
`walkforward_comparison.csv` (consolida E5 nos 3). Gate S18. Camada de execução `# pragma: no cover`.

## E7 — Finding `findings/sprint_21_walkforward_honest.md`
Estrutura spec §3/E7: TL;DR (degradação % + interpretação), tabela de métodos (E5), resultados por
ticker (folds + viz), tabela de param_stability, **interpretação e decisão** (cenários <20% / 20-50% /
>50%), e atualização do RELATORIO_TECNICO. **Disciplina híbrida S19/S20:** se a substituição do
"Sharpe 1.72" for indicada, **mostro o diff e pergunto ANTES** de tocar; tabelas históricas (3.1/7.x)
intactas; reescrita profunda → Marco do Bloco I. Pergunta aberta do meta-labeler (S20) reiterada.

---

## PARALELIZAÇÃO & CACHE (risco "tempo" = Alto na spec §5)

**Orçamento:** Optuna `n_trials=100` × 5 folds × 3 tickers ≈ 1 500 backtests de ~0.3–0.6s (janelas
504–1500 barras) ≈ **10–20 min sequencial**. Aceitável sem paralelizar. Estratégia em camadas:

1. **Cortar o espaço, não força bruta:** Optuna TPE (default) em vez de grid 729 — maior alavanca.
2. **Carregar dados UMA vez por ticker**; fatiar janelas em memória (sem re-download; cache parquet do
   `fetch_real_data` já cobre o download).
3. **Memo explícito por execução:** dict `(_params_key, is_start, is_end) -> metrics`, `_params_key =
   tuple(sorted(params.items()))`. Evita reavaliar combos repetidos que o TPE reamostra dentro do fold.
   (Não uso `lru_cache` direto porque a janela é um DataFrame não-hashable; memoizo pelas posições
   inteiras + params.) Limpo o memo por ticker.
4. **Paralelização opt-in (não default):**
   - **Grid mode:** `multiprocessing.Pool(n_jobs)` mapeando `_eval_combo` (já picklable, módulo-level)
     sobre os combos do fold; **DataFrame da janela via `initializer`/global**, não por-task (evita
     pickling caro). Guard `if __name__=="__main__"` (Windows spawn, CLAUDE.md §6.3).
   - **Optuna:** mantenho `n_jobs=1` (determinismo do `TPESampler(seed)`; paralelizar quebra
     reprodutibilidade e é frágil no Windows). Folds são sequenciais (anchored expande IS).
5. **Default `n_jobs=1`** (determinístico, seguro). `n_jobs>1` documentado como trade-off
   velocidade×determinismo, só para grid mode.

---

## CHECKPOINTS — proposta: **4** (o peso computacional + a sensibilidade do RELATORIO pedem)

- **CP1 — PLANO (este).** Commit `docs(planning): sprint 21 plan`.
- **CP2 — NÚCLEO + TESTES (sem rede).** E1 (`generate_folds`, `optimize_window`,
  `walk_forward_with_reopt`, dataclasses), E2, E3, E4 (10 testes). Descomenta pyproject. Suite
  561 → ~571, zero regressão. PARA, relatório. **Não executa dados reais.**
- **CP3 — COMPARAÇÃO (E5), só ^BVSP.** `compare_walkforward_methods.py`; valida a maquinaria
  antigo-vs-honesto e traz os **primeiros números reais** (^BVSP). PARA, relatório com a tabela.
- **CP4 — EXECUÇÃO 3 TICKERS (E6) + FINDING (E7).** Roda ^BVSP/^GSPC/VALE3; preenche o finding;
  **diff do RELATORIO_TECNICO mostrado e perguntado ANTES** (híbrida). PARA, relatório final. **Sem merge.**

> Se preferir 3 CPs, fundo CP3+CP4. Recomendo 4: isola o custo de compute do E6 e dá um ponto de
> revisão dos números do ^BVSP antes de gastar nos 3 tickers + decisão do RELATORIO.

---

## DECISÕES APROVADAS (Jeferson, CP1 → CP2) ✅

1. **param_space: 6 params (3⁶=729), Optuna default.** ✅ Os seis (regime: `adx_threshold`,
   `hurst_threshold`, `macro_direction_ret_min`; saída: `atr_stop_multiplier`, `atr_target_multiplier`,
   `chandelier_atr_mult`). Optuna corta o espaço; 10-20 min aceitável.
2. **`metric_to_optimize = sharpe_dsr` (deflado).** ✅ Otimizar pelo Sharpe cru re-introduziria o
   overfitting que o sprint mede; o DSR é a métrica honesta.
3. **Base `SPRINT13_PARAMS` SEM meta-labeler/Fibonacci.** ✅ Continuidade S19/S20. **Repetir a
   disclosure de escopo no finding** (como o S20).
4. **RELATORIO_TECNICO (E7): VIA HÍBRIDA.** ✅ **NÃO** substituir o `1.72` direto (quebraria a
   disciplina S18-S20). Números originais **intactos** como registro histórico; **nota de remissão +
   Sharpe OOS honesto AO LADO** do 1.72; **diff mostrado e aprovado ANTES** de aplicar; reescrita
   profunda → Marco do Bloco I.
5. **Gate S18: aborta o ticker se vier sintético** (não fabrica). ✅ Registrar no finding se algum
   ticker foi abortado por falta de dado real.

**Estrutura: 4 checkpoints aprovada.** ✅ Atenção redobrada aos testes E4 **#1 (AR(1) → degradação≈0)**
e **#2 (aleatório → alta degradação)** — rede de segurança metodológica. Se tocar perto de
`optimizer.py`, confirmar zero regressão em `tests/.../test_optimizer.py`.

---

## Verificação (fim do sprint)
```bash
pytest tests/unit/test_walkforward_honest.py -v      # 10 passam
pytest tests/ -q                                     # ~571
python -m walkforward_honest --ticker ^BVSP --n_folds 5
python scripts/compare_walkforward_methods.py
ls findings/sprint_21_data/   # 3 JSON + walkforward_comparison.csv + 3 PNG (ignorados)
```
