# Governança de IA

Este é o projeto de extensão, captura protegida e analytics da Governança neste monorepo.

- `extension/`: extensão Chrome atual para ChatGPT e Claude.
- `server/`: serviço HTTP independente da extensão, com autenticação, captura, analytics próprios, inspeção e integração com Google Sensitive Data Protection. Não executa nem importa o proxy do Codex.

Instale as dependências do servidor com `python -m pip install -r governanca/server/requirements.txt` e inicie-o com `python -m governanca.server.app` na raiz do repositório.

`server/capture_app/` é dono dos endpoints, persistência e analytics das interações capturadas. Os contratos de identidade e o histórico Alembic são compartilhados em `../shared/identity/` e `../shared/migrations/`. A Governança mantém a inspeção obrigatória e as decisões de política no próprio servidor, sem importar o proxy ou a análise departamental do Maximus.
