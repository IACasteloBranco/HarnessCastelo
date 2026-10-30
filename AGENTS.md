# Maximus: trabalho no backend

O Maximus é um monólito modular. `gateway/` recebe HTTP e faz o proxy; `backend/` contém admissão de runs, persistência, autorização, conhecimento e governança. O chat segue `gateway/chat.py` → `backend/chat.py` → `backend/store.py` → `gateway/forwarder.py` → Codex. Preserve os contratos dessas camadas ao mudar um fluxo.

## Invariantes dos runs

- A admissão aplica identidade, atribuição de credencial, quota e idempotência antes de chamar o Codex.
- `run_events` usa ordinais contínuos por run, inclusive quando a busca de conhecimento produz outro turno. `usage_json` soma o consumo dos turnos; `finish_transport` define o desfecho.
- Um run aberto tem lease renovado durante o stream. A recuperação ocorre ao admitir ou gerir a conversa, sob bloqueio da linha, após perda do heartbeat. Runs antigos com lease nulo exigem revisão manual.
- Falha de captura deixa o run `incomplete` com código de erro. Consulte [decisões de segurança](docs/backend-security-decisions.md) antes de mudar a política de continuidade da resposta.

## Limites de confiança

- O proxy usa allowlist de cabeçalhos; o servidor define a autorização enviada ao Codex.
- A busca de conhecimento revalida colaborador e departamento depois dos embeddings e mantém o bloqueio até formar o resultado.
- Políticas de aceite de privacidade, catálogo de modelos e permissões sensíveis dependem das decisões registradas em [decisões de segurança](docs/backend-security-decisions.md).

## Verificação

Execute testes com mocks e `HARNESS_TEST_DATABASE_URL` apontando para PostgreSQL descartável. Para mudanças no esquema, valide upgrade, downgrade e `alembic check` nesse banco. Preserve os índices já criados pelas migrações; os quatro índices de conversas, retenção e runs também constam dos modelos SQLAlchemy.
