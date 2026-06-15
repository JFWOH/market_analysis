# Finding Sprint 21 — Walk-Forward Honesto

**Status**: 🟢 preenchido (execução real, dados yfinance)
**Data**: 2026-06-10
**Autor**: Jeferson Wohanka
**Sprint relacionado**: `sprints/sprint_21_walkforward.md`
**Tag pós-finding**: `v0.21.0`

---

## TL;DR

> ## ⚠️ NÃO HÁ SHARPE OOS HONESTO POSITIVO EM NENHUM DOS 3 TICKERS — E O IS POSITIVO SÓ EXISTE QUANDO FABRICADO POR RE-OTIMIZAÇÃO ⚠️
>
> **Walk-forward com re-otimização honesta (anchored, 14 folds, IS 504+ barras, OOS 252,
> embargo 20, seleção por DSR deflado, 2010→2026): o Sharpe OOS médio é NEGATIVO nos três
> tickers — ^BVSP −0.21, ^GSPC −0.41, VALE3 −1.65. O método antigo/fixo (params escolhidos
> sobre o histórico inteiro) nem sequer produz IS positivo (^BVSP −0.09, ^GSPC −0.20,
> ambos `is_nao_positivo`; VALE3 inavaliável: 0 trades em todas as janelas). A única forma
> de obter IS Sharpe positivo é re-otimizar por janela — e esse IS (+0.12 / +0.04) COLAPSA
> para OOS negativo, com degradação >100% (cruza zero) e param_stability 0.25–0.46.
> O "Sharpe 1.72" reportado historicamente não sobrevive a nenhuma forma de walk-forward
> honesto nesta base: o que a re-otimização encontra é ruído, não edge.**

**Sharpe OOS honesto (o número de referência que a spec pede): ^BVSP = −0.21** (média de
14 janelas OOS anuais, 2012→2026). ^GSPC = −0.41. VALE3 = −1.65 (só 3/14 janelas avaliáveis).

Fecha o arco do Bloco I: S19 (sem edge OOS a custo zero) → S20 (sem alpha a decompor,
β≈0) → **S21 (qualquer IS positivo é artefato de seleção; OOS honesto negativo nos três).**

---

## Metodologia

- **Walk-forward anchored** (`walkforward_honest.py`): IS começa em 2010-01-04 e expande
  (504 barras + k·252); OOS = 252 barras seguintes; **embargo 20 barras** entre IS e OOS.
- **Re-otimização por fold**: Optuna TPE (`TPESampler(seed=42)`), **50 trials/fold**,
  espaço discreto de 6 knobs regime+saída (3⁶ = 729 combos):
  `adx_threshold {20,25,30}`, `hurst_threshold {0.50,0.55,0.60}`,
  `macro_direction_ret_min {0.05,0.08,0.12}`, `atr_stop_multiplier {1.0,1.5,2.0}`,
  `atr_target_multiplier {2,3,4}`, `chandelier_atr_mult {2,3,4}`.
- **Seleção deflada**: `metric_to_optimize='sharpe_dsr'` — Deflated Sharpe Ratio
  (Bailey & López de Prado 2014, reuso de `Backtester.deflated_sharpe_ratio`) com
  `n_trials` = nº de configs avaliadas no fold. Otimizar pelo Sharpe cru re-introduziria
  o overfitting que o sprint mede.
- **Método "antigo/fixo" (E5)**: reconstruído — otimiza UMA vez sobre o histórico inteiro
  (mesmos 50 trials/DSR) e aplica o combo fixo nas MESMAS janelas OOS. Achado do CP1: os
  scripts legados (`walk_forward_real.py` etc.) **não** são "params fixos" (re-otimizam
  por fold com grid minúsculo, sem embargo, non-anchored) — nenhum serve de referência
  executável; a comparação só é justa reconstruindo o fixo no mesmo dataset/param_space.
- **Base do sistema**: `SPRINT13_PARAMS` (custos 0.1%+0.1%, `min_trades=3` por janela).
- **Dados reais** (gate S18): ^BVSP 4070 barras, ^GSPC 4131, VALE3.SA 4081 — todos
  `yfinance`, 2010-01-04→2026-06; **nenhum ticker abortado por dado sintético**.
- **Rede de segurança metodológica (E4)**: testes #1 (sinal estável → degradação ≈ 0) e
  #2 (ruído puro → degradação alta) passam — o método distingue sinal de ruído; o que ele
  mede aqui é overfitting real, não artefato da régua.

### Disclosures obrigatórias

1. **Desvio da spec: 14 folds, não 5.** A spec E6 fixava 5 folds; com IS=504/OOS=252
   anchored, 5 folds cobririam só 2010→2017 — deixando de fora **2017-2026, exatamente o
   regime onde S19/S20 encontraram ausência de edge**. Decisão (aprovada no CP4): n_folds
   máximo que o histórico comporta (=14 nos três tickers), cobrindo 2010→2026
   (^BVSP até 2026-05-11, ^GSPC até 2026-02-11, VALE3 até 2026-04-27).
2. **Consistência CP3 vs E6: 100 → 50 trials.** O E5 do CP3 (^BVSP, 5 folds) usou 100
   trials; o E6 usa **50** (custo do anchored expanding com 14 folds; decisão aprovada —
   o CP3 já mostrara que não há sinal a encontrar; 50 vs 100 muda quão fundo se cava um
   poço vazio). O resultado qualitativo é idêntico nos dois settings (IS positivo fabricado
   → colapso OOS): CP3 IS +0.42→OOS −0.16; E6 IS +0.12→OOS −0.21. `param_stability` pode
   variar levemente entre 50 e 100 trials; a leitura de instabilidade não muda (0.50 vs 0.46).
3. **Escopo do sistema: SEM meta-labeler nem Fibonacci** (continuidade S19/S20). O que se
   re-otimiza são os knobs de regime+saída sobre a base Sprint-13. A contribuição do
   meta-labeler permanece **não-medida** (pergunta aberta ao Marco, registrada no S20).
4. **`is_nao_positivo` ≠ falha do método.** Quando o IS Sharpe é ≤0, a "degradação
   relativa" é não-interpretável (não há performance a degradar) e o rótulo honesto é
   `is_nao_positivo`. **"Não há edge no IS para degradar" é um achado mais forte que
   overfitting** — nem dragando dados o método fixo acha IS positivo.
5. **PF OOS é instável nesta base** (células com 2.5–5.1 apesar de Sharpe negativo):
   janelas OOS de 252 barras têm pouquíssimos trades; um único ganho grande infla o PF.
   **Sharpe é a métrica primária** deste finding; PFs por janela são reportados nos JSONs.
6. **Folds pulados são registro, não omissão** (`skip_invalid_folds`, opt-in adicionado no
   CP4 por causa do VALE3): fold cuja janela IS não produz nenhum combo com ≥3 trades é
   contado e excluído das médias. VALE3: 11/14 pulados no honesto; 14/14 no fixo.
7. **O único OOS médio positivo do E6 — ^GSPC fixo, +0.063 — é ruído, não edge.**
   Registrado por ir contra a narrativa geral (auditoria registra o que aparece): o combo
   foi selecionado com IS ≤0 (−0.20, `is_nao_positivo` — sem sinal a transferir), logo um
   OOS marginalmente positivo, em 14 janelas anuais de pouquíssimos trades, é variância de
   amostragem, não vantagem. Detalhe na §^GSPC dos resultados E6.

---

## Comparação de métodos (E5) — a estimativa do data dredging

Mesmo dataset, mesmo param_space, mesmos folds:

| Ticker | Método | folds válidos | IS Sharpe | OOS Sharpe | stability | Degradação |
|---|---|---|---|---|---|---|
| ^BVSP | antigo (fixo) | 14/14 | −0.089 | −0.166 | 1.00 | n/a (`is_nao_positivo`) |
| ^BVSP | **honesto (re-otim)** | 14/14 | **+0.115** | **−0.207** | 0.46 | −280% (artefato) |
| ^GSPC | antigo (fixo) | 14/14 | −0.201 | +0.063 | 1.00 | n/a (`is_nao_positivo`) |
| ^GSPC | **honesto (re-otim)** | 14/14 | **+0.044** | **−0.405** | 0.45 | −1013% (artefato) |
| VALE3.SA | antigo (fixo) | **0/14** | — | — | — | **INAVALIÁVEL** (0 trades) |
| VALE3.SA | **honesto (re-otim)** | 3/14 | −0.289 | −1.648 | 0.25 | n/a (`is_nao_positivo`) |

**Δ OOS Sharpe (honesto − fixo): ^BVSP −0.04 · ^GSPC −0.47.** Re-otimizar honestamente é
**igual ou pior** OOS do que fixar params — a re-otimização não captura sinal nenhum; só
compra variância. A leitura do data dredging aqui é dupla:

- **No IS**: a diferença entre o IS do honesto (+0.12/+0.04) e o do fixo (−0.09/−0.20) é
  o tamanho da ilusão que a seleção de hiperparâmetros fabrica — **+0.20 a +0.25 de Sharpe
  IS que não existe**.
- **No OOS**: nada disso sobrevive. O OOS honesto é negativo nos três tickers.

(Referência CP3, ^BVSP 5 folds/100 trials, janelas 2010→2017: honesto IS +0.416 → OOS
−0.162, deg −139%; fixo IS −0.083 `is_nao_positivo`; Δ OOS −0.158. Registro completo em
`findings/sprint_21_data/` no histórico do commit `45f7cdc`.)

---

## Resultados por ticker (E6)

### ^BVSP — 4070 barras, 14 folds (OOS cobrindo 2012→2026)

IS por fold (honesto): +0.67, +0.52, +0.40, +0.16, +0.33, … → média **+0.115**. OOS
correspondentes: −1.23, +0.47, +0.26, +0.03, −0.34, … → média **−0.207**. Os params
ótimos trocam entre blocos de folds (adx 30 → adx 20; stability 0.46): cada janela
"encontra" um ótimo diferente — assinatura de ajuste a ruído.
Gráfico: `findings/sprint_21_data/walkforward_bvsp.png` · JSON: `compare_bvsp.json`.

### ^GSPC — 4131 barras, 14 folds (OOS cobrindo 2012→2026)

O caso mais didático: IS honesto quase nulo (+0.044) e OOS fortemente negativo (−0.405).
Em um índice em bull secular (2010-2026), o sistema re-otimizado **ainda** entrega OOS
negativo — o filtro de regime + saídas, com qualquer combinação dos 6 knobs, não converte
o trend do S&P em retorno. **Registro honesto:** o fixo tem OOS **+0.063** — o único OOS
médio positivo do E6, e vai contra a narrativa geral, por isso fica registrado. Não é
edge: o combo foi selecionado com IS **negativo** (−0.20, `is_nao_positivo` — a seleção
não continha sinal), e um OOS marginalmente positivo após seleção sem sinal, em 14
janelas de poucos trades, é ruído de amostragem. A leitura que sobra: não operar quase
nada (fixo) é melhor que re-otimizar (−0.405). Stability 0.45.
Gráfico: `walkforward_gspc.png` · JSON: `compare_gspc.json`.

### VALE3.SA — 4081 barras, 14 folds → quase-não-amostra

- **Fixo: INAVALIÁVEL** — o combo global não gera ≥3 trades em NENHUMA das 14 janelas.
- **Honesto: 11/14 folds pulados** (nenhum dos 50 combos testados atinge 3 trades nas
  janelas IS de 2012→2022!). Nos 3 folds avaliáveis (IS terminando 2022-2024): IS Sharpe
  **negativo** nos três (−0.49, −0.18, −0.20) e OOS pior (−1.68, −2.79, −0.48).
- Eco direto do S19 (16 trades em 8 anos; PETR4 com 3): **o sistema simplesmente não opera
  este ticker**. Não é "robusto em VALE3" nem "frágil em VALE3" — é não-amostra.
Gráfico: `walkforward_vale3.png` · JSON: `compare_vale3.json`.

---

## Param stability score (E3)

| Ticker | stability (honesto, top-3 Jaccard entre folds consecutivos) |
|---|---|
| ^BVSP | 0.46 |
| ^GSPC | 0.45 |
| VALE3.SA | 0.25 (sobre 3 folds) |

Todos **abaixo do limiar de robustez (0.6)** do template: os conjuntos ótimos não se
repetem entre janelas vizinhas. Combinado com OOS negativo, é o quadro completo de
overfitting: params instáveis + IS que não se transfere.

---

## Interpretação e decisão

### Qual cenário do template se aplica?

Nenhum dos três cenários previstos ("degradação <20% → validada"; "20-50% → faixa de
incerteza"; ">50% → overfitted, buscar config robusta") descreve o resultado, porque todos
pressupõem **um IS positivo a degradar**. O resultado real é mais fundamental:

> **Não há configuração no espaço regime+saída da Sprint-13 que produza Sharpe OOS
> positivo em qualquer dos 3 tickers, em 14 janelas anuais de 2012→2026.** O IS positivo
> só existe como artefato de seleção (e o DSR deflado já o encolhe: +0.12 e +0.04 são
> resíduos de ruído); a degradação formal, onde calculável, excede 100% (cruza zero).

### Decisão explícita sobre a config atual (critério de aceitação)

**A config Sprint-13 NÃO é validável por walk-forward honesto.** Decisão registrada:

1. **Não manter** a narrativa de "OOS Sharpe 1.72" — o número não é reproduzido por
   nenhuma metodologia honesta nesta base (ver reconciliação abaixo).
2. **Não ajustar dentro deste espaço de params** — o E6 mostra que não há ótimo estável
   a encontrar nos 6 knobs centrais; "buscar config mais robusta" dentro do mesmo sistema
   teria de explorar outra coisa (escopo, sinais, mercados), não outra célula do grid.
3. **Deferir a decisão estrutural ao Marco do Bloco I** (pós-S22), com o conjunto completo
   S18-S22. **Registro formal para o Marco** (em vez de propor um "Sprint 21.5" isolado):
   qualquer reabilitação precisa (a) de hipótese nova (não re-tuning), e (b) do experimento
   meta-labeler+Fibonacci ON pendente do S20.

### Reconciliação com o "Sharpe 1.72" (por que não é contradição direta)

O 1.72 do `RELATORIO_TECNICO.md` (tabela 1.1/7.x) vem de janela OOS **curta (~7 meses)**,
em condição de bull, com meta-labeler ativo e modelo de custo diferente (ver reconciliação
do S19). O S21 mede outra coisa: **estabilidade temporal sob re-otimização honesta em 14
janelas anuais**. O S21 não "prova que o 1.72 foi inventado"; prova que ele **não
generaliza** — é uma janela favorável, não uma propriedade do sistema.

---

## Atualização do RELATORIO_TECNICO.md

**Via híbrida (disciplina S18-S20), diff apresentado e aprovado ANTES de aplicar; números
originais intactos como registro histórico; reescrita profunda deferida ao Marco:**

- [x] §1.1 (Perfil estratégico): blockquote ⚠️ ao lado da tabela — Sharpe OOS honesto
  (S21: ^BVSP −0.21 / ^GSPC −0.41 / VALE3 n/a) AO LADO do +1.72, com cross-ref.
- [x] §5.7.3 (Validação OOS): nota metodológica — o walk-forward histórico re-otimizava
  com grid mínimo/sem embargo; o S21 introduz `walkforward_honest.py` (anchored, embargo,
  DSR) e os resultados divergem materialmente.
- [x] §8.1 (Quants): bullet com os números S21 + cross-ref a este finding.

(Checkboxes marcados quando o diff for aprovado e aplicado — aplicados no commit de cross-refs S21.)

---

## Limitações deste finding

- **50 trials sobre 729 combos** (~7% do espaço por fold; TPE adaptativo): suficiente para
  a conclusão qualitativa (CP3 com 100 trials deu o mesmo quadro), mas os "best_params"
  por fold não são ótimos globais certificados.
- **Janelas OOS anuais (252 barras)** têm poucos trades → métricas por fold ruidosas
  (PF especialmente; disclosure 5). As médias entre 14 folds mitigam, não eliminam.
- **Embargo de 20 barras** sem meta-labeler é conservador o bastante; com meta-labeler
  ativo, releitura necessária (risco apontado na spec §5).
- **Espaço de busca restrito a regime+saída** (decisão CP1): sizing, ensemble interno e
  meta-labeler não foram re-otimizados.
- **VALE3 com 3 folds** não suporta conclusão estatística além de "não-amostra".

---

## Próximos passos

- [ ] **Marco do Bloco I (pós-S22)**: decisão estrutural sobre a config Sprint-13 à luz de
  S18-S21; registro de que reabilitação exige hipótese nova + experimento meta-labeler.
- [x] Aplicar cross-refs do RELATORIO_TECNICO (após aprovação do diff). → §1.1, §5.7.3, §8.1.
- [ ] Sprint 22 (bears expandido): última peça do Bloco I.
