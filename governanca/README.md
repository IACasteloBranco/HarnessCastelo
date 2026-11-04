# Governança de IA

Este é o projeto de extensão, captura protegida e analytics da Governança neste monorepo.

- `extension/`: extensão Chrome atual para ChatGPT e Claude.
- `server/`: API e painel próprios, com autenticação, captura, analytics, inspeção e integração com Google Sensitive Data Protection. Não executa nem importa o Maximus.

Instale as dependências do servidor com `python -m pip install -r governanca/server/requirements.txt`. Configure `GOVERNANCA_DATABASE_URL` para o banco exclusivo da Governança, execute `python -m alembic -c governanca/alembic.ini upgrade head` e inicie com `python -m governanca.server.app` na raiz do repositório. Para criar organização, departamento e colaborador ou redefinir senha temporária, consulte `python -m governanca.server.identity.operator --help`; o arquivo de senha deve ficar fora do repositório e ser entregue por canal seguro, sem inseri-la no terminal ou no Git.

`server/capture_app/` é dono da captura e do analytics. `server/identity/` é dono de contas, sessões, departamentos e investigações; as migrações da Governança ficam em `server/migrations/`. A Governança usa banco próprio, configurado explicitamente por `GOVERNANCA_DATABASE_URL`, e não lê o `.env` da raiz nem tabelas do Maximus. `compose.yaml` provisiona um PostgreSQL separado em `127.0.0.1:55435` por padrão; defina `GOVERNANCA_POSTGRES_PASSWORD` antes de iniciá-lo. A planilha `docs/Codigos_dos_departamentos_agrupados.xlsx` é apenas referência: não é importada automaticamente nem altera o banco existente.

Investigações antigas sem colaborador-alvo não podem ser aprovadas ou usadas: rejeite as pendentes e abra novas solicitações com o alvo definido antes da aprovação. As já aprovadas sem alvo expiram sem acesso ao conteúdo; não vincule alvos retroativamente.
