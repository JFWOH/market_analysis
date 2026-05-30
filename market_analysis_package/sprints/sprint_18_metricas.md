# Sprint 18 — Desambiguação de Métricas de Drawdown

**Bloco**: I (Auditoria)
**Duração estimada**: 3-4 dias úteis
**Pré-requisito**: nenhum
**Status**: pending
**Tag ao fechar**: `v0.18.0`

---

## 1. Contexto

O `RELATORIO_TECNICO.md` apresenta Max Drawdown (MDD) consistentemente abaixo de 1% em condições normais, e razões dramaticamente baixas (0.01× a 0.05×) contra Buy-and-Hold em crashes históricos. Esses números são suspeitos por ambiguidade de base de cálculo:

- **MDD sobre equity total** inclui caixa ocioso. Se o sistema fica fora do mercado 70% do tempo, o caixa amortece quedas e o número resultante é artificialmente baixo.
- **MDD sobre capital empregado em risco** mede apenas o que aconteceu com o dinheiro efetivamente exposto. É a métrica que importa para um operador.

A diferença pode ser de uma ordem de magnitude. Sem desambiguação, o headline do produto está em terreno frágil para qualquer auditoria séria.

---

## 2. Objetivo

Introduzir cálculo paralelo das duas métricas no motor (`backtester.py` e novo módulo `metrics.py`), com testes anti-regressão, e re-emitir todos os relatórios históricos do `bear_market_validation.py` com as duas colunas explícitas.

---

## 3. Entregáveis

### E1 — Módulo `metrics.py` (novo)

Função pura, sem side effects, sem I/O:

```python
def compute_drawdown_dual(
    equity_curve: pd.Series,
    position_value_curve: pd.Series,
) -> dict:
    """
    Calcula drawdown em duas bases.
    
    Parameters
    ----------
    equity_curve : pd.Series
        Valor total da conta a cada barra (caixa + posições marcadas a mercado).
    position_value_curve : pd.Series
        Valor absoluto das posições abertas a cada barra. Zero quando flat.
    
    Returns
    -------
    dict com chaves:
        - total_equity_mdd : float (positivo, em %)
        - capital_at_risk_mdd : float (positivo, em %) ou NaN se sempre flat
        - time_in_market_pct : float em [0, 100]
        - total_equity_mdd_duration_bars : int
        - capital_at_risk_mdd_duration_bars : int
        - mdd_explanation : str (texto explicativo curto)
    """
```

Implementação:
- `total_equity_mdd`: rolling peak da `equity_curve`, drawdown = (curr - peak) / peak.
- `capital_at_risk_mdd`: considera apenas as barras onde `position_value_curve > 0`. Calcula equity "como se" todo dinheiro estivesse em risco — divide a variação por position_value, não por total.
- Mais precisamente: para cada barra com posição aberta, calcula PnL relativo ao capital empregado naquela barra. Constrói curva sintética de "equity por unidade de capital empregado" e tira MDD dela.

### E2 — Integração em `backtester.py`

Modificação não-quebrante:

- Backtester rastreia `position_value_curve` ao longo da simulação (já tem dados; só precisa expor).
- Ao final, chama `compute_drawdown_dual` e adiciona as chaves ao resultado.
- Campo `max_drawdown_pct` existente é **mantido** (igual a `total_equity_mdd`) para retrocompatibilidade.
- Novos campos: `max_drawdown_capital_at_risk_pct`, `time_in_market_pct`.

### E3 — Suite de testes `tests/unit/test_metrics.py`

Mínimo 12 casos, cobrindo:

1. **Always-long**: posição aberta em 100% das barras → `total_mdd == capital_at_risk_mdd`.
2. **Nunca opera**: position_value sempre 0 → `total_mdd == 0`, `capital_at_risk_mdd == NaN`, `time_in_market_pct == 0`.
3. **50% no mercado, perdedora**: drawdown nominal X em equity total deveria ser ~2X em capital-at-risk.
4. **50% no mercado, vencedora**: assimetria — capital-at-risk pode ter drawdown maior em períodos curtos.
5. **Posição short** com lucro em queda de mercado.
6. **Partial exit a 1R**: fechou 50% da posição → position_value cai pela metade.
7. **Gap overnight**: descontinuidade entre fechamento e abertura.
8. **Determinismo**: mesmo input ≡ mesmo output (rodar duas vezes, comparar).
9. **Edge case**: equity curve constante (nenhuma variação) → MDDs zerados.
10. **Edge case**: position_value parcial (entre 0 e 1 unidade — fracionário).
11. **Coerência matemática**: `total_equity_mdd <= capital_at_risk_mdd` quando há caixa ocioso.
12. **Reproducibilidade do bear 2008**: input conhecido produz output idêntico ao referencial calculado manualmente.

Todos os testes devem ser determinísticos (seeds fixas onde houver RNG).

### E4 — Script `scripts/rerun_bear_validation_dual_mdd.py`

- Lê os 7 cenários do `bear_market_validation.py` atual.
- Executa cada um com config Sprint-13 reference.
- Coleta as duas métricas de MDD.
- Saída CSV: `findings/sprint_18_data/bears_dual_mdd.csv` com colunas: `cenario, periodo, ticker, total_mdd_pct, capital_at_risk_mdd_pct, time_in_market_pct, num_trades, sharpe`.
- Visualização: gráfico de barras agrupadas (matplotlib) salvo como PNG.

### E5 — Relatório `findings/sprint_18_mdd_dual.md`

Estrutura obrigatória:

```markdown
# Finding Sprint 18 — Drawdown em Base Dupla

## TL;DR
[1-2 frases. Se diferença for >5×, escrever em letras grandes.]

## Tabela renovada (7 cenários × 2 bases)
[Markdown table]

## Interpretação honesta
[1-2 parágrafos. Sem maquiagem.]

## Impacto no posicionamento do produto
[Se diferença for material, listar o que muda: 
sumário executivo do RELATORIO_TECNICO.md, 
banner condicional em relatórios futuros, etc.]

## Decisões tomadas
[Bulleted list das atualizações feitas no mesmo PR]
```

---

## 4. Critério de Aceitação

Binário, verificável por checklist:

- [ ] Suite completa passa: `pytest tests/ -q` (519+ testes anteriores + 12 novos)
- [ ] `compute_drawdown_dual` tem cobertura ≥ 95%
- [ ] CSV existe em `findings/sprint_18_data/bears_dual_mdd.csv`
- [ ] Visualização PNG existe e é legível
- [ ] `findings/sprint_18_mdd_dual.md` existe com as 4 seções obrigatórias
- [ ] Backtester emite ambos os campos em todos os outputs
- [ ] Docstring de `compute_drawdown_dual` explica claramente as duas bases (com exemplo numérico)
- [ ] Se `capital_at_risk_mdd >= 5 * total_equity_mdd` em qualquer cenário, sumário executivo do `RELATORIO_TECNICO.md` está atualizado no mesmo PR

---

## 5. Riscos

| Risco | Probabilidade | Mitigação |
|---|---|---|
| Definição de "capital em risco" ambígua em partial exits | Média | Decisão documentada no docstring: usar valor nominal das posições abertas em cada barra, somando-as |
| Posição short distorce cálculo | Média | Testes específicos para shorts (caso 5 da suite) |
| Findings forçam reescrita do headline | Alta | Esperado e desejado. Aceitar |

---

## 6. Notas para o Claude Code

- **Não modificar testes existentes** do backtester. Apenas adicionar asserções para os novos campos.
- **Função `compute_drawdown_dual` é pura**: sem I/O, sem prints, sem leitura de arquivo. Recebe dados, devolve dict.
- **Usar numpy vetorizado**, não loops Python sobre a Series.
- **Convenção de sinal**: drawdown é reportado como número positivo (5.2 significa 5.2%, não -5.2).
- **Para short**: PnL em capital-at-risk é calculado como `-1 * (price_change / entry_price)` em cada barra.
- Em caso de dúvida sobre interpretação financeira, consultar o relatório de findings antes de implementar — algumas decisões precisam ser documentadas como ADR mini.

---

## 7. Comandos de validação

```bash
# Após implementar
pytest tests/unit/test_metrics.py -v
pytest tests/ -q

# Re-execução dos cenários
python scripts/rerun_bear_validation_dual_mdd.py

# Verificar saída
ls findings/sprint_18_data/
cat findings/sprint_18_mdd_dual.md | head -30
```

---

## 8. Estimativa detalhada

| Tarefa | Estimativa |
|---|---|
| E1 — módulo metrics.py | 0.5 dia |
| E3 — testes (12 casos) | 1 dia |
| E2 — integração backtester | 0.5 dia |
| E4 — script + visualização | 0.5-1 dia |
| E5 — escrita do relatório | 0.5-1 dia |
| Buffer (debug, validação) | 0.5 dia |
| **Total** | **3-4 dias** |
