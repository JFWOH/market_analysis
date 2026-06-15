# Sprint 22 — Validação em Bears Não-Canônicos (Plano — Checkpoint 1)

> **Passo 0 (disciplina S18-S21):** este plano é commitado como
> `docs/sprint_plans/sprint_22_plan.md` (`docs(planning): sprint 22 plan`) ANTES de qualquer código.
>
> **Pré-requisito:** Sprint 21 fechado (`v0.21.0`) e mergeado em `main`. Branch `sprint-22-bears`
> a partir da `main` pós-S21. **Baseline de testes (medido nesta sessão): 576.**
> **Destino final deste arquivo:** `docs/sprint_plans/sprint_22_plan.md` (layout flat).

## Context

Os 7 bears canônicos (GFC/COVID/2022/2015 — S16/S18) são amostra com viés de sobrevivência
narrativa. O S22 expande para **15 cenários** em 5 categorias e roda a **base auditada Sprint-13**
(decisão A), expondo honestamente **onde o sistema falha** — com foco na categoria que tipicamente
quebra trend-following (mean-reverting brutal). Fecha o Bloco I e alimenta o `MARCO_BLOCO_I.md`
(Dimensão 1 Preservação + Dimensão 3 Robustez). **Sem otimização** — só backtest com config fixa
em duas bases de custo (S19) e MDD dual (S18), com IC bootstrap por cenário.

---

## PASSO 1 — Sondagem de disponibilidade de dados (READ-ONLY, executada @ 2026-06-14)

Via `scripts.fetch_real_data.download(...)` (retorna `(df, source)`; `source=='synthetic'` = sem dado real).
**Confirmado primeiro: o fallback sintético NÃO é cacheado (`fetch_real_data.py:254` só persiste o ramo
`yfinance`) — a sondagem não pode envenenar o cache.**

| # | id | ticker | período | disponível? | barras | qualidade (barras/bdays) |
|---|---|---|---|---|---|---|
| 1 | gfc_2008_bvsp | ^BVSP | 2008-06→2009-06 | OK (yfinance) | 269 | 0.96 |
| 2 | gfc_2008_gspc | ^GSPC | 2008-06→2009-06 | OK | 272 | 0.97 |
| 3 | covid_2020_bvsp | ^BVSP | 2020-01→2020-06 | OK | 122 | 0.95 |
| 4 | bear_2022_ixic | ^IXIC | 2022-01→2022-12 | OK | 251 | 0.97 |
| 5 | br_bear_2015 | ^BVSP | 2015-01→2016-01 | OK | 265 | 0.94 |
| 6 | argentina_2001 | ^MERV | 2001-01→2002-06 | OK | 349 | 0.89 (menor) |
| 7 | russia_2014 | IMOEX.ME | 2014-06→2015-06 | OK | 267 | 0.95 |
| 8 | turkey_2018 | XU100.IS | 2018-05→2019-01 | OK | 187 | 0.95 |
| 9 | asia_1997_hsi | ^HSI | 1997-07→1998-12 | OK | 371 | 0.95 |
| 10 | china_2015 | 000001.SS | 2015-06→2016-02 | OK | 182 | 0.93 |
| 11 | japan_lost_decade | ^N225 | 1995-01→2003-12 | OK | 2219 | 0.95 |
| 12 | euro_sovereign_2011 | ^STOXX50E | 2011-05→2012-12 | OK | 417 | 0.96 |
| 13 | br_mini_bear_2011 | ^BVSP | 2011-04→2012-06 | OK | 310 | 0.95 |
| 14 | vol_spike_2018_feb | ^GSPC | 2018-01→2018-04 | OK (mais fina, 72) | 72 | 0.96 |
| 15 | brl_crisis_2020_h2 | BRL=X | 2020-07→2020-12 | OK | 132 | 1.01 |

**Resultado: 15/15 OK, dados reais, 0 INDISPONÍVEL, 0 sintético, 0 PARCIAL relevante.**
**Achado factual que molda o sprint:** isso **contradiz a tabela de riscos da spec §5** (que dava ^MERV,
IMOEX.ME como "Alta prob." de indisponíveis) e o **template do finding** (que pré-escreveu "Asia 1997
HSI indisponível"). A narrativa `data_unavailable` está **vazia hoje**. Logo o resultado honesto do S22
dependerá de **onde o sistema falha**, não de lacunas de dados.
**Nota metodológica (inversão da premissa — registrar também no finding E5):** a spec foi escrita esperando
**falha por dados ausentes**; o teste real do S22 é **onde o SISTEMA falha**. A sondagem 15/15 **FORTALECE** o
finding — onde houver falha, terá sido **com dados reais, sem desculpa de lacuna**. O caminho `data_unavailable`
fica testado (robustez) mas provavelmente vazio.
*Caveats:* (a) snapshot — yfinance é instável (CLAUDE.md §6.1); re-sondar na execução (CP3). (b) A sondagem
cobriu só a janela de eval; o **warmup** (~90 barras antes de `start`) para os mais antigos (asia_1997 →
precisa ~1997-01; japan → ~1994) é risco residual: se faltar, indicadores auto-aquecem dentro do eval
(limitação documentada). vol_spike (72 barras) fica OK pois o warmup vem de 2017, fora da janela fina.

---

## PASSO 2 — Investigação de reuso (DRY) — confirmado em código

1. **MDD dual (S18):** `metrics.compute_drawdown_dual(equity_curve: pd.Series, position_value_curve: pd.Series) -> dict`
   (`metrics.py:37`). Chaves: `total_equity_mdd`, `capital_at_risk_mdd` (NaN se nunca houve posição),
   `time_in_market_pct`, `*_duration_bars`, `mdd_explanation`. **Curvas vêm de `bt.equity`, `bt.position_value`,
   `bt.equity_dates`**, recortadas à janela de eval — exatamente o protótipo `scripts/rerun_bear_validation_dual_mdd.py:56`
   (`_run_scenario`), que é a **base direta do E2**.
2. **Custos (S19):** `Backtester(..., commission_pct=<frac>, slippage_pct=<frac>)`. Constantes em
   `cost_sensitivity.py:336`: `BASELINE_SLIP=0.001` (0.1%), `STRESS_SLIP=0.003` (0.3%). **Reuso leve:** rodar
   o backtest 2× por cenário (slip 0.1% e 0.3%) — não preciso do `cost_sensitivity_sweep` (grid 4×5), só dos
   dois pontos. Comissão baseline 0.1% (`commission_per_trade=0.001`, como o protótipo de bears).
3. **Original (DRY):** `scripts/bear_market_validation.py` fornece `SPRINT13_PARAMS`, `CAPITAL=100_000`,
   `_bh_metrics(closes, capital) -> {ret_pct, mdd_pct}` (Alpha vs B&H) e o idioma warmup→eval que o `_v2` estende.
4. **YAML + validação:** `pyyaml` 6.0.3 é **dep core** (`pyproject:44`) → OK. **`pydantic` 2.13.4 importa no venv
   local MAS só está no extra `api` (`pyproject:66`), não em core/dev** → usá-lo arriscaria quebrar coleta de
   testes num `pip install -e .[dev]` mínimo/CI. Spec §6 permite "pydantic **ou** validação manual" →
   **decisão: validação manual** (dataclass + checagens), zero dependência nova, reversível.
5. **Bootstrap CI:** `stress_test.bootstrap` simula caminho de equity (não é IC de Sharpe). Reuso o **idioma**
   (`rng.choice(rets, replace=True)`, `np.random.default_rng(seed)`, retornos por trade ≈ `pnl/amount` do
   `bt.trades`) num helper novo, puro e testável `bootstrap_sharpe_ci(...)`.
6. **Padrão de script testável (S19):** `scripts/` não tem `__init__.py`, mas os testes fazem
   `from scripts.cost_sensitivity import ...` com `sys.path.insert(_ROOT)`. `bear_market_validation_v2.py`
   segue o mesmo molde: **núcleo-biblioteca puro no topo** (testável, sem rede) + **plots lazy (matplotlib Agg)**
   + **camada de execução/CLI `# pragma: no cover`**. Teste importa `from scripts.bear_market_validation_v2 import ...`.
   **Sem mudança em `pyproject.toml`** (script em `scripts/`, não é módulo raiz; yaml é dado).

---

## DECISÕES (A/B/C) — resolvidas com o Jeferson

- **A — Config = `SPRINT13_PARAMS`, rótulo "base auditada".** Continuidade S18-S21. Reuso o registry
  `sprint_13_reference` de `cost_sensitivity._load_config`. Declarar no finding: "validada" = *a base que passou
  pela auditoria*, **não** "a que foi aprovada" (o S21 mostrou que nenhuma config tem edge OOS).
- **B — Piso de cobertura (aprovado, refinado no CP1): ≥12/15 executados com sucesso + os 5 cenários de controle
  (GFC ^BVSP/^GSPC, COVID, 2022, 2015) executando + ≥3/4 categorias-núcleo representadas.** Escolhi **12** dentro da
  discricionariedade dada (10 vs 12): falha de execução com **dado disponível é bug a corrigir**, não a tolerar — 12
  deixa margem só para uns poucos edge-cases de dado antigo. O piso é rede para falhas de **EXECUÇÃO** (não de dados;
  dados estão 15/15). **Exigência DURA e não-negociável: `mean_reverting_brutal` OBRIGATORIAMENTE representada nos
  cenários executados** — é a categoria-teste central (calcanhar do trend-following); o "≥3/4 categorias" sozinho
  permitiria justamente ela ficar de fora. **O finding NÃO é válido sem `mean_reverting_brutal`.** ("4 categorias-núcleo"
  = crash_linear, regional, mean_reverting_brutal, lost_decade; forex é à parte.)
- **C — Forex `BRL=X` incluído como SANITY-CHECK SEPARADO (categoria `forex`), interpretado SEPARADAMENTE.** Enquadrar como
  **confirmação COM DADOS** de uma inadequação já reconhecida (RELATORIO: macro_lock falha em forex; S14 deu 0 trades),
  **não** como "mais uma falha". **Fora das contagens de aprovado/reprovado.** Mostrar a limitação concretamente
  vale mais que citá-la.

---

## E1 — `scenarios/bears_v2.yaml` (cria a pasta `scenarios/`) + validador manual

- 15 cenários do spec §3/E1, com **uma alteração aprovada (C):** `brl_crisis_2020_h2` passa de
  `category: regional` → `category: forex`; **enum estendido p/ 5 valores**:
  `{crash_linear, regional, mean_reverting_brutal, lost_decade, forex}`.
- Contagem por categoria (fonte de verdade = campo `category` do YAML):
  crash_linear **6** (5 controles + `china_2015`), regional **4**, mean_reverting_brutal **3**, lost_decade **1**, forex **1**.
  *Nota:* o template do finding rotula crash_linear como "5 — controle"; na execução são **6** (incluir `china_2015`;
  sub-rotular os 5 originais como "controle").
- Validador no `bear_market_validation_v2.py` (puro, testável):

```python
ALLOWED_CATEGORIES = {"crash_linear", "regional", "mean_reverting_brutal", "lost_decade", "forex"}
REQUIRED_FIELDS = ("id", "name", "ticker", "start", "end", "category")

@dataclass(frozen=True)
class Scenario:
    id: str; name: str; ticker: str
    start: str; end: str; category: str
    notes: str = ""

def load_scenarios(yaml_path: str) -> list[Scenario]:
    """Carrega + valida bears_v2.yaml (pyyaml, sem pydantic). Levanta ValueError com
    mensagem clara em: campo obrigatório ausente, category fora do enum, data não-ISO
    (YYYY-MM-DD), start>=end, ou id duplicado."""
```

## E2 — `scripts/bear_market_validation_v2.py` (núcleo-biblioteca + plots + execução)

**Núcleo puro (testável, sem rede):**
```python
def run_scenario(df: pd.DataFrame, scenario: Scenario, base_params: dict,
                 capital: float = CAPITAL, slippage_pct: float = 0.001,
                 commission_pct: float = 0.001, warmup_bars: int = 90,
                 strategy_factory=None) -> dict:
    """Roda UM cenário sobre df in-memory (já com warmup antes de scenario.start).
    Backtest (CombinedStrategy+SPRINT13 base) → métricas. MDD dual + time-in-market
    via compute_drawdown_dual nas curvas RECORTADAS à janela de eval [start,end]
    (fiel ao S18). sharpe/pf/win_rate/return e num_trades da rodada completa.
    Alpha vs B&H via _bh_metrics no eval. strategy_factory = seam de teste (como S19)."""

def bootstrap_sharpe_ci(trade_returns: np.ndarray, n_samples: int = 1000,
                        rng: np.random.Generator | None = None, ci: float = 0.95
                        ) -> tuple[float, float, float]:
    """(low, point, high). Resample com reposição dos retornos por trade; Sharpe
    por amostra; percentis (1-ci)/2 e 1-(1-ci)/2. rng=default_rng(42) default."""

def classify_status(sharpe: float, mdd_car_pct: float) -> str:
    """'aprovado' (sharpe>0 e mdd_car<10) | 'reprovado' (sharpe<0 ou mdd_car>15)
    | 'inconclusivo' (faixa intermediária). Forex usa o mesmo cálculo mas é
    marcado/contado à parte na camada de execução (decisão C)."""
```
**Plots lazy (matplotlib Agg)** — assinaturas em E3.
**Execução (`# pragma: no cover`):**
```python
def run_all(yaml_path="scenarios/bears_v2.yaml", base_slip=0.001, stress_slip=0.003,
            output_dir="findings/sprint_22_data", fetcher=None, seed=42) -> pd.DataFrame:
    """Para cada cenário: fetcher(ticker, start-warmup, end) → se source=='synthetic',
    marca data_unavailable (gate S18) e segue. Senão run_scenario @ base e @ stress slip.
    Escreve bears_complete.csv; gera os 5 plots; loga skips. fetcher default = download
    (injeção = seam de teste p/ E4 #5, sem rede)."""

def main(argv=None) -> int:   # pragma: no cover — CLI/rede
```

## E3 — Visualizações (5 PNGs em `findings/sprint_22_data/plots/`, gitignored)

1. `forest_sharpe.png` — Sharpe + IC95% bootstrap por cenário, **ordenado/agrupado por categoria**, linha vertical em 0.
2. `forest_mdd_car.png` — MDD capital-at-risk por cenário (linhas em 10% e 15% = limiares de status).
3. `forest_alpha.png` — Alpha vs B&H (pp) por cenário, linha em 0.
4. `scatter_sharpe_tim.png` — Sharpe × time-in-market %, cor por categoria.
5. `category_medians.png` — barras: mediana de Sharpe por categoria.

Paleta (spec §6): crash_linear azul, regional laranja, mean_reverting_brutal vermelho, lost_decade cinza,
**forex roxo** (5ª categoria). Helper genérico `forest_plot(rows, value_key, ci_keys=None, out_path, ...)`
reaproveitado nos 3 forests. **Adicionar `findings/sprint_22_data/plots/*.png` ao `.gitignore`** (consistência S18/S21:
PNG regenerável não-versionado; CSV versionado).

## CSV — `findings/sprint_22_data/bears_complete.csv` (1 linha/cenário, versionado)

`scenario_id, name, ticker, category, start, end, source, n_bars, num_trades, sharpe,
sharpe_ci_low, sharpe_ci_high, profit_factor, win_rate, return_pct, alpha_vs_bh_pp,
mdd_equity_pct, mdd_car_pct, time_in_market_pct, sharpe_slip03, pf_slip03, status`
(`status ∈ {aprovado, reprovado, inconclusivo, data_unavailable}`; cenários `forex` carregam status calculado
mas são tabulados/contados à parte).

## E4 — `tests/unit/test_bear_validation.py` (≥6, determinísticos, SEM rede)

1. `test_yaml_schema_valid` + `test_yaml_schema_rejects_bad` — `load_scenarios` aceita YAML válido (campos/enum/datas) e
   levanta `ValueError` em campo ausente / category inválida / data não-ISO / id duplicado. *(spec #1)*
2. `test_synthetic_crash_expected_mdd` — série de crash sintética → `run_scenario` dá MDD na faixa esperada. *(spec #2)*
3. `test_synthetic_meanrev_system_trades` — série mean-reverting sintética → `num_trades > N` (sistema opera). *(spec #3)*
4. `test_bootstrap_ci_deterministic_seed` — mesma seed → IC idêntico; o IC contém o Sharpe pontual. *(spec #4)*
5. `test_data_unavailable_marks_row_no_crash` — `fetcher` injetado devolve `source='synthetic'` → linha marcada
   `data_unavailable`, sem exceção, execução continua. *(spec #5)*
6. `test_forest_plot_generates` — `forest_plot` grava PNG em tmp sem erro para dados de brinquedo. *(spec #6)*

Extra (cobertura, não conta no mínimo 6): `test_classify_status_faixas` (aprovado/reprovado/inconclusivo),
`test_forex_excluded_from_tally`, `test_alpha_vs_bh_sign`. Fixtures: OHLCV sintético via `np.random.default_rng(seed)`
+ seam `strategy_factory`/`fetcher`. Cobertura do núcleo **≥85%** (execução/CLI sob `# pragma: no cover`, técnica S19/S21).

## E5 — Finding `findings/sprint_22_bears_complete.md` (preencher o template existente)

- TL;DR com números reais; **se `mean_reverting_brutal` falhar como categoria, isso vai em letras grandes** (critério §4).
- Tabelas por categoria: crash_linear (6, com `china_2015`), regional (4), mean_reverting_brutal (3), lost_decade (1),
  **forex (1) — seção à parte (decisão C)**, enquadrada como confirmação de limitação já citada (S14 0-trades), não como falha.
- 5 forest plots embutidos; seção "Cenários onde FALHOU" com diagnóstico; seção `data_unavailable`
  (hoje vazia — registrar "0 indisponíveis na execução de <data>; path de robustez testado, não acionado").
- **Nota metodológica da inversão** (premissa pessimista da spec invertida pela sondagem 15/15 → o teste é onde o
  SISTEMA falha, com dados reais) e **disclosure de qualidade dos dados antigos** (gaps/ajustes duvidosos em
  ^HSI 1997 / ^MERV 2001 / ^N225 anos 90, conferidos no CP3).
- **RELATORIO_TECNICO §7 — VIA HÍBRIDA (disciplina S18-S21):** **NÃO** hard-replace do "7/7"; **mostrar o diff e
  aprovar ANTES**; adicionar subseção "Validação expandida cross-categoria" + tabela ampla + cross-ref; números
  originais intactos; reescrita profunda deferida ao `MARCO_BLOCO_I.md`. (A spec §3/E5 diz "substituir"; a disciplina
  S18-S21 sobrepõe — registrar a divergência.)
- Alimenta o `MARCO_BLOCO_I.md` (criado **após** S22, spec §9): ≥80% aprovados→Cenário A; 50-80%→B; <50%→C.

---

## CHECKPOINTS — 3 (conforme combinado)

- **CP1 — PLANO (este).** Commit `docs(planning): sprint 22 plan` (este arquivo em `docs/sprint_plans/`). Read-only.
- **CP2 — NÚCLEO + TESTES (sem rede).** E1 (yaml + validador manual), E2 (núcleo-biblioteca + plots), E4 (≥6 testes).
  Suite **576 → ~585**, zero regressão. PARA, RELATÓRIO DE CHECKPOINT (formato ORCHESTRATION). **Não executa dados reais.**
- **CP3 — EXECUÇÃO + FINDING.** Re-sondar dados; rodar os 15 cenários reais (E2 execução), gerar `bears_complete.csv`
  + 5 PNGs (E3), preencher o finding (E5); **diff do RELATORIO_TECNICO §7 mostrado e aprovado ANTES** de aplicar.
  PARA, RELATÓRIO FINAL. **Sem merge** (decisão do Jeferson, ORCHESTRATION §6/§97).

---

## Verificação (fim do sprint)
```bash
pytest tests/unit/test_bear_validation.py -v      # >=6 passam
pytest tests/ -q                                  # ~585, zero regressão
python scripts/bear_market_validation_v2.py       # 15 cenários, dados reais
ls findings/sprint_22_data/                        # bears_complete.csv + plots/ (5 PNG, ignorados)
ruff check . && mypy .
```

## Riscos / notas
- **Warmup dos antigos** (asia_1997, japan_1995): se faltar dado pré-janela, indicadores auto-aquecem no eval
  (documentar). Demais cenários têm warmup folgado.
- **vol_spike (72 barras)** é a janela mais fina — IC bootstrap mais largo; reportar com a ressalva.
- **Qualidade ≠ disponibilidade (disclosure CP3/finding):** 15/15 disponíveis não garante 15/15 de boa qualidade.
  No CP3, conferir gaps/ajustes duvidosos nos períodos antigos (^HSI 1997, ^MERV 2001, ^N225 anos 90) e registrar
  no finding qualquer cenário de qualidade questionável — honestidade sobre dados antigos. Não muda o CP2.
- **Custos regionais** modelados como B3 (0.1%/0.3%) — otimista p/ Turquia/Argentina (limitação, herdada do S19).
- **Sequenciamento:** S22 pressupõe `v0.21.0` mergeado em `main`; `sprint-22-bears` deve sair da `main` pós-S21.
  Confirmar a base do branch antes do CP2.
- **Sem pyproject change** (script em `scripts/`); **sem dependência nova** (validação manual, não pydantic).
