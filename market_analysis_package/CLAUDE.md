# CLAUDE.md — Convenções do Projeto `market_analysis`

Este arquivo instrui o Claude Code (e qualquer outro agente automatizado) sobre as convenções inegociáveis do projeto. Leia até o fim antes de tocar em qualquer código.

---

## 1. Identidade do Projeto

`market_analysis` é um sistema quantitativo de pesquisa, backtesting e simulação de operações em mercados financeiros. O motor é maduro (519+ testes, 17 sprints históricos, arquitetura em camadas). O programa atual de desenvolvimento (Sprints 18-33) tem três objetivos sequenciais:

1. **Auditar** a base atual com honestidade (Bloco I — Sprints 18-22)
2. **Endurecer** para uso operacional sério (Bloco II — Sprints 23-26)
3. **Construir** a interface gráfica web local (Bloco III — Sprints 27-33)

O motor é **soberano** sobre a UI. A UI consome o motor, nunca o contrário.

---

## 1.5 Layout do Projeto (LEIA ANTES DE CRIAR QUALQUER ARQUIVO)

**Este projeto usa layout FLAT.** Os módulos Python vivem soltos na raiz do repositório, NÃO dentro de uma pasta `market_analysis/`. Não existe pasta `src/`. Não existe pacote `market_analysis/` importável.

Isso é uma decisão consciente, herdada dos 17 sprints anteriores. A migração para layout `src/` foi avaliada e **deliberadamente adiada** — migrar 18+ módulos top-level e centenas de imports nos testes não traz ganho funcional e tem risco alto. Ver discussão no histórico do projeto.

### Tradução de caminhos

Quando qualquer arquivo de sprint mencionar um caminho com prefixo `market_analysis/`, **leia como raiz**:

| O sprint diz | Você cria em |
|---|---|
| `market_analysis/metrics.py` | `metrics.py` (raiz) |
| `market_analysis/audit_log.py` | `audit_log.py` (raiz) |
| `market_analysis/risk_guard.py` | `risk_guard.py` (raiz) |
| `market_analysis/db/schema.sql` | `db/schema.sql` (subpasta `db/` na raiz) |
| `market_analysis/db/repository.py` | `db/repository.py` |

Os arquivos do pacote **já foram traduzidos** para o layout flat — os caminhos aparecem corretos (`metrics.py`, `db/schema.sql`, etc.). Esta nota existe para o caso de você encontrar referência antiga.

### Imports

Imports são diretos, sem prefixo de pacote:

```python
from strategy import CombinedStrategy        # correto
from backtester import Backtester            # correto
from db.repository import Repository         # correto (db/ é subpasta)

# ERRADO — NÃO FAÇA:
from market_analysis.strategy import CombinedStrategy
```

### Module-run

```bash
python -m audit_log verify ...      # correto
python -m watchdog --heartbeat ...  # correto
```

### Exceções (pastas que SÃO pacotes de verdade)

- **`db/`** — subpasta para tema banco de dados (schema, repository). Tem `__init__.py`.
- **`gui/`** — criada no Bloco III (Sprint 27). É pacote real com submódulos (`routes/`, `static/`, `templates/`). Tem `__init__.py`.
- **`tests/`** — já existe. Estrutura `tests/unit/`, `tests/integration/`, `tests/e2e/`.

### Registro em pyproject.toml

Ao criar um módulo novo na raiz, **descomente a linha correspondente** em `[tool.setuptools] py-modules` no `pyproject.toml`. Há comentários marcando qual sprint adiciona qual módulo.

### NÃO FAÇA

- ❌ Não crie pasta `market_analysis/` na raiz.
- ❌ Não crie pasta `src/`.
- ❌ Não migre módulos existentes para dentro de um pacote.
- ❌ Não escreva `from market_analysis.X import Y` em código novo.

Se em algum momento parecer que faria sentido reorganizar para `src/`, **PARE e pergunte ao Jeferson** — é decisão arquitetural grande, não algo a fazer no meio de um sprint.

---

## 2. Regras Invioláveis

### 2.1 Testes obrigatórios
Nenhum código novo entra em `main` sem teste correspondente. A suite completa precisa passar antes de qualquer commit:

```bash
pytest tests/ -q
```

Tempo alvo: < 60 segundos para `tests/unit/`, < 5 minutos para suite completa incluindo integração.

### 2.2 Ausência de look-ahead bias
Qualquer cálculo sobre série temporal precisa de teste explícito anti-lookahead. O padrão canônico:

```python
def test_indicator_no_lookahead():
    """Calcular o indicador sobre df[:i] deve dar mesmo resultado
    que calcular sobre df completo e tomar o valor na posição i."""
    full = compute_indicator(df)
    for i in range(50, len(df)):
        partial = compute_indicator(df.iloc[:i+1])
        assert partial.iloc[-1] == pytest.approx(full.iloc[i])
```

Sem esse teste, a feature não é aceita.

### 2.3 Opt-in para features novas
Toda nova feature entra com flag desligado por padrão em `CombinedStrategy.DEFAULT_PARAMS`. Padrão de nomenclatura: `use_<feature>` (boolean) e parâmetros relacionados com prefixo da feature.

Exemplo: ao adicionar HMM regime classifier (hipotético):
```python
DEFAULT_PARAMS = {
    # ... existentes
    "use_hmm_regime": False,        # opt-in
    "hmm_n_states": 3,
    "hmm_min_prob": 0.6,
}
```

Comportamento default precisa ser idêntico ao anterior à feature.

### 2.4 Imutabilidade do audit log
A partir do Sprint 23, todo `audit_log.py` é append-only. Nunca usar UPDATE/DELETE em entries existentes. Corrupção detectada deve ser reportada, não silenciada.

### 2.5 Adapter pattern para a UI
A partir do Sprint 27, `gui/` **nunca** importa diretamente dos módulos do motor (`strategy`, `backtester`, etc.). Tudo passa por `gui/adapter.py`, que é o único ponto de contato. Razão: isolar UI de mudanças internas do motor.

Anti-pattern proibido:
```python
# gui/routes/live.py
from strategy import CombinedStrategy  # PROIBIDO
```

Padrão correto:
```python
# gui/routes/live.py
from gui.adapter import get_strategy_runner  # OK
```

### 2.6 Determinismo
Nenhuma chamada a `random.seed()` global. Cada Monte Carlo recebe RNG explícito (`np.random.default_rng(seed)`). Hashing de parâmetros para identificação de runs.

---

## 3. Estrutura de Commits

Mensagens seguem [Conventional Commits](https://www.conventionalcommits.org/) adaptado:

```
<tipo>(<escopo>): <descrição curta - max 72 chars>

<descrição longa com contexto, 1-3 parágrafos>

<bloco de evidência>

Sprint: <NN>
Tests: <N> novos, <T> total
Coverage: <X%>
```

Tipos permitidos:
- `feat` — nova feature
- `fix` — correção de bug
- `refactor` — mudança sem alterar comportamento
- `test` — adição/correção de testes
- `docs` — apenas documentação
- `perf` — otimização de performance
- `audit` — descoberta de finding ou correção pós-auditoria

Escopos comuns: `strategy`, `backtester`, `meta_labeler`, `gui`, `audit_log`, `risk_guard`, `db`, `ci`.

---

## 4. Workflow por Sprint

Cada sprint segue rigorosamente este fluxo:

1. **Ler** `sprints/sprint_NN_<slug>.md` completo. Não pular para implementação.
2. **Criar branch** `sprint-NN-<slug>` a partir de `main` atualizada.
3. **Implementar entregáveis na ordem listada** (E1, E2, E3...). Não pular ordem.
4. **Cada entregável tem PR próprio** com:
   - Testes correspondentes
   - Descrição referenciando o entregável (E1, E2...)
   - Suite completa passando
5. **Ao fim do sprint**, criar `findings/sprint_NN_<topic>.md` se aplicável (todos os sprints do Bloco I têm findings).
6. **Merge final** em `main` com tag `v0.<NN>.0`.
7. **Sprint só está fechado** quando todos critérios de aceitação do artefato estão marcados.

---

## 5. Comandos Canônicos

```bash
# === Setup ===
python -m venv venv
venv\Scripts\activate                  # Windows
pip install -e ".[dev]"

# === Testes ===
pytest tests/unit -q                   # rápido (~45s, 519+ testes)
pytest tests/ -q                       # completo (unit + integration)
pytest tests/e2e --headed              # Playwright com janela visível
pytest --cov=. --cov-report=html

# === Lint e tipos ===
ruff check .
ruff format .
mypy . 

# === UI local ===
python -m gui.server                   # Flask em http://127.0.0.1:5000
python -m gui.desktop                  # pywebview standalone

# === Análises (Bloco I) ===
python scripts/rerun_bear_validation_dual_mdd.py
python scripts/cost_sensitivity.py --ticker ^BVSP
python scripts/factor_decomposition.py --config sprint_13_reference
python -m walkforward_honest --ticker ^BVSP --n_folds 5

# === Database ===
python scripts/migrate_json_to_sqlite.py    # migração one-shot
sqlite3 data/market_analysis.db < db/schema.sql

# === Audit log ===
python -m audit_log verify logs/audit/2026-05-13.jsonl
python -m audit_log replay --from "2026-05-13T10:00" --to "2026-05-13T11:00"

# === CI local (mimicar GitHub Actions) ===
pre-commit run --all-files
```

---

## 6. Pontos de Atenção do Projeto

### 6.1 yfinance é instável
Sempre cache local primeiro. Função `fetch_real_data.py` já implementa retry exponencial. Antes de qualquer análise nova, conferir se cache está fresco.

### 6.2 SQLite em concorrência
A partir do Sprint 25, SQLite roda com WAL mode habilitado (já configurado em `db/schema.sql`). Uma sessão de simulação pode ter múltiplas escritas simultâneas; testar concorrência é parte do critério de aceitação do Sprint 25.

### 6.3 SocketIO + multiprocessing em Windows
Windows usa `spawn` (não `fork`) para novos processos. Bibliotecas com estado global (matplotlib, algumas versões de pandas em modo C-extension) podem causar crashes silenciosos. Ver `docs/decisions/ADR-001-web-local.md` para mitigações. Sempre validar arquitetura ponta-a-ponta com mock antes de UI rica.

### 6.4 Audit log é append-only
A partir do Sprint 23: nunca usar UPDATE/DELETE em entries. Para "corrigir" uma entry errada, gerar nova entry de tipo `CORRECTION` referenciando a anterior por hash.

### 6.5 yfinance latência em modo live
Dados intraday brasileiros têm latência de 15-20 minutos pela API gratuita. UI Live (Sprint 32) deve mostrar isso claramente. Não há simulação "tick-by-tick" no escopo atual.

### 6.6 Custos de transação são parametrizáveis
A partir do Sprint 19, qualquer relatório que reporte performance deve mencionar slippage e comissão usados. Defaults: 0.1% slippage, 0.1% comissão. Para análises sérias, rodar com 0.3% slippage como pessimista realista.

---

## 7. Quando em Dúvida

Em ordem:

1. **Consultar** `docs/decisions/ADR-*.md` para decisões arquiteturais já tomadas.
2. **Consultar** `RELATORIO_TECNICO.md` para entender o motor.
3. **Consultar** `sprints/ROADMAP.md` para contexto do sprint atual.
4. **Consultar** `sprints/sprint_NN_*.md` específico do sprint em execução.
5. **Verificar** se há `findings/` de sprints anteriores que afetam o trabalho atual (a auditoria do Bloco I pode reescrever premissas).
6. **Se ainda em dúvida**, perguntar — não inventar.

---

## 8. Anti-patterns Proibidos

São coisas que parecem boas ideias mas quebram o projeto. Não fazer, mesmo se parecer "só desta vez":

- **Modificar testes existentes para fazer passar** novo código. Os 519 testes legados são verdade estabelecida. Se um teste antigo quebra, o problema está no código novo.
- **Adicionar dependência binária** (TA-Lib, pandas-ta com C-extensions, etc.). Reproducibilidade exige Python puro + numpy/pandas/scipy.
- **Hardcoded paths** (`H:\\PYTHON\\...`). Tudo via configuração ou variáveis de ambiente.
- **Print debugging em produção**. Use `logger` do módulo. `print()` em código merged é regressão.
- **`from X import *`**. Imports explícitos sempre.
- **Mutar `DEFAULT_PARAMS`** em qualquer lugar fora da definição original. Pass por kwargs ou copy.
- **Quebrar API pública** sem deprecation warning de pelo menos 1 sprint.
- **Otimização prematura**. Profiling antes de otimizar.

---

## 9. Glossário de Decisões Já Tomadas

Para evitar re-litigar decisões:

- **Web local sobre desktop nativo**: ver ADR-001.
- **SQLite sobre PostgreSQL nesta fase**: ver ADR-002.
- **Append-only audit log com hash chain**: ver ADR-003.
- **Replay Histórico antes de Paper Trading Live**: ver `sprints/ROADMAP.md` seção 5.
- **MDD em duas bases (total + capital-at-risk)**: ver Sprint 18.
- **Fase de auditoria (Bloco I) antes de hardening**: ver Princípio 1 do `sprints/ROADMAP.md`.

---

## 10. Filosofia

Três frases que resumem o espírito do projeto:

> "Verdade antes de feature." — Bloco I existe para descobrir o que é real.

> "Reversibilidade." — Todo sprint pode ser revertido sem quebrar anteriores.

> "A UI é consumidora, não criadora." — Motor define a verdade; UI a visualiza.

Quando em dúvida sobre uma decisão de design, retornar a essas três frases.
