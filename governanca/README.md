# Governança de IA

Este é o projeto de extensão, captura protegida e analytics da Governança neste monorepo.

- `extension/`: extensão Chrome atual para ChatGPT e Claude.
- `server/`: API e painel próprios, com autenticação, captura, analytics, inspeção e integração com Google Sensitive Data Protection. Não executa nem importa o Maximus.

Instale as dependências do servidor com `python -m pip install -r governanca/server/requirements.txt`. Configure `GOVERNANCA_DATABASE_URL` para o banco exclusivo da Governança, execute `python -m alembic -c governanca/alembic.ini upgrade head` e inicie com `python -m governanca.server.app` na raiz do repositório. Para criar organização, departamento e colaborador ou redefinir senha temporária, consulte `python -m governanca.server.identity.operator --help`; o arquivo de senha deve ficar fora do repositório e ser entregue por canal seguro, sem inseri-la no terminal ou no Git.

`server/capture_app/` é dono da captura e do analytics. `server/identity/` é dono de contas, sessões, departamentos e investigações; as migrações da Governança ficam em `server/migrations/`. A Governança usa banco próprio, configurado explicitamente por `GOVERNANCA_DATABASE_URL`, e não lê o `.env` da raiz nem tabelas do Maximus. `compose.yaml` provisiona um PostgreSQL separado em `127.0.0.1:55435` por padrão; defina `GOVERNANCA_POSTGRES_PASSWORD` antes de iniciá-lo.

Para migrar a relação local: depois de `alembic upgrade head`, execute `python -m governanca.server.identity.roster_migration docs/Codigos_dos_departamentos_agrupados.xlsx --password-file CAMINHO_PRIVADO_FORA_DO_REPOSITORIO.csv`. O comando exige banco Governança local vazio, valida a planilha integralmente e cria numa transação a organização, os 21 departamentos e os 61 colaboradores com senhas temporárias. Também cria o departamento isolado `GOVERNANCA-TESTE` e vincula a ele `COLAB-000` como `governance`: essa função já inclui o analytics de auditoria, sem atribuir dois papéis a uma conta. A vinculação da máquina requer departamento; o departamento de teste impede que as capturas desse usuário sejam atribuídas a um departamento real. A planilha ignorada e o CSV de credenciais não devem ir para o Git; entregue as senhas individualmente por canal seguro e apague o CSV depois. Nenhuma migração Alembic embute nomes, códigos pessoais ou senhas.

Cada nova solicitação registra finalidade e colaborador-alvo e concede ao próprio solicitante acesso às interações daquele colaborador por uma hora. O portal não possui etapa de aprovação nem gera documentação; o conteúdo detalhado só é exibido ao solicitante enquanto o acesso estiver válido.
