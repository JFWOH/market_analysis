# ADR-002 — Persistência: SQLite com WAL sobre Alternativas

**Status**: Accepted
**Data**: 2026-05-13
**Decisores**: Jeferson Wohanka
**Consulta técnica**: Claude (Anthropic)

---

## Contexto

O `paper_trader.py` original persiste em arquivos JSON soltos. À medida que o programa avança para sessões persistentes, comparação A/B, histórico filtrável e potencialmente concorrência de processos (UI + watchdog + simulador), é necessária uma fundação de dados mais sólida.

Alternativas avaliadas:

### Opção A — Continuar com JSON
Manter o status quo. Apenas adicionar lock files para evitar corrupção.

### Opção B — SQLite + WAL
Banco embarcado, zero-server, ACID, Write-Ahead Logging para concorrência.

### Opção C — PostgreSQL local (Docker)
PostgreSQL em container, escala para multi-machine no futuro.

### Opção D — DuckDB
OLAP embarcado, ótimo para queries analíticas; menos tradição para escrita transacional.

### Opção E — TinyDB / dataset (NoSQL local)
Document store em JSON com índices. Stack mais leve que SQLite.

---

## Decisão

**Adotamos a Opção B — SQLite com WAL mode, schema versionado, sem ORM.**

---

## Racional

### Por que NÃO Opção A (JSON)

1. **Last-write-wins corruptor silencioso**: dois processos escrevendo o mesmo arquivo causam perda de dados sem aviso.
2. **Queries arbitrárias caras**: para "sessões com PF > 1.5 entre março e maio", é necessário carregar tudo e iterar.
3. **Sem integridade referencial**: trade aponta para session_id em string; nada garante consistência.
4. **Sem transações**: crash entre escrita de duas estruturas relacionadas deixa estado inconsistente.
5. **Crescimento de arquivo**: JSON inteiro é reescrito a cada modificação — não escala.

### Por que NÃO Opção C (PostgreSQL)

1. **Sobreengenharia para single-user solo**. PostgreSQL exige instalação separada, configuração de usuários, gestão de conexões, backup operacional.
2. **Container Docker adiciona pré-requisito de deploy** ao usuário final — incompatível com objetivo de "clique no .exe e funciona".
3. **Acoplamento ao Docker** complica empacotamento via PyInstaller.
4. **Performance**: para volumes do projeto (estimativa: ~10M rows após 5 anos de uso intenso), SQLite é mais que suficiente.
5. **Migração futura é trivial** se necessário: SQL Standard cobre 95% dos casos; mudança de driver.

### Por que NÃO Opção D (DuckDB)

1. **Excelente para analytics, marginal para OLTP**. Inserções frequentes (cada signal, cada equity snapshot) são caso de uso transacional, não analítico.
2. **WAL menos maduro** que SQLite (em 2026).
3. **Comunidade menor**; menos respostas em StackOverflow quando coisas dão errado.
4. **Consideração**: DuckDB pode entrar futuramente como **camada de leitura analítica**, com SQLite como fonte de verdade. Não no escopo atual.

### Por que NÃO Opção E (TinyDB / dataset)

1. **Não é ACID**. Risco de perda de dados em crash.
2. **Performance degrada** rapidamente com > 100k documentos.
3. **Sem queries SQL** — usa APIs proprietárias, dificulta análise ad-hoc.
4. **Comunidade pequena**; manutenção incerta.

### Por que SIM Opção B (SQLite + WAL)

1. **Zero-server, zero-install**: faz parte da stdlib do Python. Funciona em qualquer ambiente sem dependência externa.
2. **ACID completo**: transações, foreign keys (com PRAGMA ligado), rollback automático.
3. **WAL mode** permite múltiplos leitores concorrentes a um escritor — exatamente nosso caso (UI lendo enquanto simulador escreve).
4. **Performance**: 50k+ INSERT/s em hardware modesto; query plans com EXPLAIN; índices arbitrários.
5. **Ferramentas excelentes**: DB Browser for SQLite (GUI), `sqlite3` CLI, integração com qualquer linguagem.
6. **Backup trivial**: copiar o arquivo. Restore: substituir o arquivo.
7. **Migração futura**: SQL portável cobre PostgreSQL/MySQL caso necessário.

### Por que SEM ORM

1. **SQL direto é mais explícito** sobre o que está acontecendo no banco — auditoria de queries é direta.
2. **Performance previsível**: nada de "lazy loading surpresa" ou "N+1 queries" ocultas.
3. **Menos uma dependência** (SQLAlchemy/Tortoise/Peewee adicionam centenas de classes ao import graph).
4. **Schema declarativo em SQL puro** (`schema.sql`) é portable e versionável diretamente.
5. **Para projeto de single-developer**, dialeto SQL é menos esforço cognitivo que aprender API de ORM.

Contrapartida: refactors de schema exigem mais cuidado manual. Mitigado por testes de migração explícitos e schema_version tracking.

---

## Consequências

### Positivas

- Concorrência segura entre UI, simulador e watchdog
- Queries analíticas eficientes (`SELECT ... WHERE pf > 1.5 ORDER BY created_at DESC LIMIT 50`)
- Backup é uma operação de cópia de arquivo
- Migração de JSON existente é uma operação one-shot (Sprint 25 entrega o script)
- Schema versionado desde dia 1: futuras alterações ganham trilho

### Negativas e mitigações

| Negativa | Mitigação |
|---|---|
| WAL files crescem em sessões longas | Auto-checkpoint default do SQLite resolve; documentado |
| Sem hot replication out-of-the-box | Aceitar para fase atual; backup periódico via cópia |
| Locks de escrita em transações longas podem bloquear leituras de view exclusiva | Transações curtas; readers em WAL não bloqueiam |
| SQL manual exige mais cuidado em refactors | Schema versionado + testes de migração; trade-off aceito |

### Riscos específicos do Windows

- **File path encoding**: usar `pathlib.Path` exclusivamente; nunca strings com `\`.
- **Antivírus pode bloquear** escrita frequente — documentar exclusão da pasta `data/`.
- **WAL não funciona em alguns sistemas de arquivo de rede** (SMB antigo). Documentar: DB deve viver em disco local, não em network share.

---

## Métricas de validação

A decisão é considerada bem-sucedida se, ao fim do Sprint 25:

- Concorrência: 4 processos escrevendo simultaneamente sem erro (teste explícito)
- Performance de leitura: query "últimas 100 sessões" retorna em < 50ms com 10k sessões no DB
- Migração: dataset JSON de teste migrado sem perda (validável manualmente)
- WAL mode: `PRAGMA journal_mode` retorna `wal` em todas as conexões

---

## Revisão

Esta ADR pode ser revista se:

1. Volume crescer além de SQLite suportar confortavelmente (> 50M rows). Improvável no horizonte de 5 anos para single-user.
2. Necessidade de multi-machine surgir (deploy SaaS, equipe distribuída). Fora do escopo do programa atual.
3. Workload virar majoritariamente OLAP (relatórios analíticos > 80% do tempo). Nesse caso, considerar DuckDB como camada de leitura.

---

## Referências

- `sprints/sprint_25_sqlite.md` — implementação
- `db/schema.sql` — schema canônico
- SQLite WAL: https://www.sqlite.org/wal.html
- "When To Use SQLite": https://www.sqlite.org/whentouse.html
