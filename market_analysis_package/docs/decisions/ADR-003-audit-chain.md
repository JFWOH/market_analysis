# ADR-003 — Audit Log: Append-Only com Hash Chain (Merkle simplificado)

**Status**: Accepted
**Data**: 2026-05-13
**Decisores**: Jeferson Wohanka
**Consulta técnica**: Claude (Anthropic)

---

## Contexto

Qualquer sistema operacional sério — particularmente em finanças — precisa de rastro auditável de decisões. O sistema atual produz logs em texto via `logger.debug/info`, que servem para debug em desenvolvimento mas falham nos três usos importantes:

1. **Compliance**: auditor precisa verificar "esta decisão foi realmente tomada neste momento?"
2. **Forensics**: pós-mortem de bug exige reconstrução fiel de eventos
3. **Replay**: capacidade de reproduzir uma sessão histórica deterministicamente

Logs de texto soltos têm três problemas estruturais:

- **Mutáveis**: nada impede `sed -i` editando entries
- **Sem garantia de ordem**: dois processos escrevendo podem entrelaçar linhas
- **Sem identidade**: não há forma de provar que entry X precedeu entry Y

Alternativas consideradas:

### Opção A — Logs em texto (status quo)
Simples, leve, mas sem nenhuma garantia.

### Opção B — Append-only com hash chain simples (Merkle-like)
Cada entry contém hash da anterior. Modificação retroativa quebra a chain de forma detectável.

### Opção C — Blockchain (distribuída ou local)
Cada entry é um "bloco" com PoW/PoS. Tamper-evident garantido por design.

### Opção D — Banco append-only com triggers no SQLite
Tabela com trigger que recusa UPDATE/DELETE. Sem hash, mas com constraint.

### Opção E — Append-only + assinatura digital
Cada entry assinada com chave privada. Verificação por chave pública.

---

## Decisão

**Adotamos a Opção B — Append-only em JSONL com hash chain SHA-256, complementado por mirror em tabela SQLite para queries rápidas.**

---

## Racional

### Por que NÃO Opção A (status quo)

Já discutido no contexto. Sem garantia de integridade, ordem, ou identidade. Insuficiente para qualquer uso operacional.

### Por que NÃO Opção C (Blockchain)

1. **Overkill drástico**. Blockchain resolve o problema de **confiança entre partes não-confiáveis**. Aqui, sistema é single-user, single-machine. Não há adversário do qual precisar provar nada.
2. **Custo computacional alto** (PoW) ou complexidade (PoS) sem ganho proporcional.
3. **Dependências pesadas**: bibliotecas blockchain Python têm long tail de transitivas.
4. **Marketing-driven**: usar "blockchain" sem necessidade real é antipattern.

### Por que NÃO Opção D (SQLite append-only via triggers)

1. **Não é tamper-evident**: triggers podem ser removidos por quem tem acesso ao DB. SQL `PRAGMA writable_schema=ON; DELETE FROM sqlite_master WHERE name='trigger_name';` desfaz.
2. **Sem prova criptográfica**: alguém com acesso ao arquivo pode modificar linhas com hex editor; trigger não detecta.
3. **Aceitável como mirror para queries**, não como fonte de verdade.

### Por que NÃO Opção E (Assinatura digital)

1. **Exige gestão de chaves** — chave privada precisa estar disponível em runtime, mas protegida.
2. **Compromisso de chave** invalida toda a história.
3. **Tamanho da entry cresce** com assinatura RSA/ECDSA (~512 bytes overhead).
4. **Complexidade desnecessária** para o threat model atual (não há rede pública).

Pode ser adicionado depois como camada extra se threat model evoluir.

### Por que SIM Opção B (hash chain SHA-256)

1. **Tamper-evident**: modificar entry N quebra hashes de N e N+1, N+2, ... até o fim. `verify_chain` detecta exatamente onde.
2. **Append-only enforced por design**: estrutura JSONL + chain forçam apêndice. UPDATE seria detectável.
3. **Verificação em tempo linear**: O(N) na quantidade de entries. Para arquivos típicos (< 100k entries/dia), milissegundos.
4. **Sem chaves**, sem complexidade de gestão.
5. **JSONL é universal**: qualquer linguagem lê, qualquer ferramenta processa (`jq`, `grep`, `awk`).
6. **Hash SHA-256 é estável e padrão**: nada exótico.

### Estrutura da chain

```
Entry 1: { ..., prev_hash="000...0" (GENESIS), this_hash=H(entry_sem_this_hash) }
Entry 2: { ..., prev_hash=H1,              this_hash=H(entry_sem_this_hash) }
Entry 3: { ..., prev_hash=H2,              this_hash=H(entry_sem_this_hash) }
...
```

Onde `H(...)` é SHA-256 do JSON canônico (chaves ordenadas) da entry sem o campo `this_hash`.

### Mirror em SQLite

Tabela `events` no DB (criada no Sprint 25) recebe cópia de cada entry, com índices apropriados. Razão: queries como "todos os SIGNAL_FILTERED desta sessão" são triviais em SQL; impraticáveis em JSONL sem tooling.

A fonte de verdade é o JSONL. O DB é otimização de leitura. Se houver divergência, JSONL ganha.

---

## Consequências

### Positivas

- Tamper-evident sem complexidade criptográfica avançada
- `verify_chain` é ferramenta única e simples — qualquer auditor entende em 5 minutos
- Replay de sessões históricas é trivial: iterar log → reconstruir estado
- Compatibilidade com qualquer ferramenta unix-style
- Performance: append é O(1) (ponteiro de hash mantido em memória)

### Negativas e mitigações

| Negativa | Mitigação |
|---|---|
| Não detecta substituição do arquivo inteiro (alguém deleta tudo e reescreve) | Aceitar limitação; complementar com backups externos no Sprint 25 |
| Não protege contra adversário com acesso de escrita | Aceitar — este não é o threat model. Append-only assume confiança no operador, foco é proteger contra erro acidental e dar trilho de auditoria |
| Arquivos JSONL crescem em sessões longas | Rotação diária (Sprint 23); arquivos antigos podem ser comprimidos com gzip |
| Performance de verify em arquivos muito grandes | Streaming verify; nunca carregar arquivo inteiro |

---

## Threat model assumido

O design protege contra:

1. **Modificação acidental** (sed, editor de texto, script com bug que altera log)
2. **Auditoria post-hoc**: "esta decisão foi realmente tomada neste momento?"
3. **Replay reverso**: reconstruir comportamento sem precisar das estruturas de runtime

O design **não** protege contra:

1. **Adversário malicioso com acesso completo** ao sistema (poderia deletar tudo)
2. **Conluio de timestamps** (NTP fake)
3. **Coerção do operador**

Esses casos exigem hardware seguro (HSM), notarização externa (blockchain real), ou múltiplas testemunhas — fora do escopo deste programa.

---

## Métricas de validação

A decisão é considerada bem-sucedida se, ao fim do Sprint 23:

- Append não bloqueia simulação por mais de 1ms por evento
- `verify_chain` em arquivo de 100k entries roda em < 5 segundos
- Modificação manual de 1 byte em entry intermediária é detectada com índice correto
- Rotação diária funciona corretamente (chain continua entre arquivos)
- Mirror SQLite é coerente com JSONL após qualquer simulação

---

## Procedimento de correção de entry errada

Não se modifica entry existente. Para "corrigir":

1. Criar nova entry de tipo `CORRECTION`
2. Payload contém: `original_hash` (hash da entry errada), `corrected_fields` (delta), `reason`
3. Ferramentas de replay tratam `CORRECTION` como override da entry referenciada

Isso preserva a chain enquanto permite correção operacional.

---

## Revisão

Esta ADR pode ser revista se:

1. Sistema passar a operar em ambiente multi-tenant / remoto (threat model muda)
2. Compliance regulatório exigir notarização externa
3. Volume crescer a ponto de SHA-256 + JSONL serem gargalo (improvável)

---

## Referências

- `sprints/sprint_23_audit_log.md` — implementação
- `docs/AUDIT_EVENTS.md` — schema de eventos (criado no Sprint 23)
- Merkle Trees: https://en.wikipedia.org/wiki/Merkle_tree (chain é caso degenerado)
- "The Tangled Web of Distributed Trust" — McConnell et al., relevância de hash chains
