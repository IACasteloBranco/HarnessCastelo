# HarnessCastelo

Proxy FastAPI para o backend Codex, com OAuth por conta, chaves de cliente, limites de uso e captura de execuções para o harness.

O código está separado em `backend/`, `gateway/` e `frontend/`. O mapa atual e os limites ainda pendentes estão em [`docs/PROJECT_CONTEXT.md`](docs/PROJECT_CONTEXT.md).

Para retomar o MVP em outra máquina, leia o [estado atual e roteiro de continuidade](docs/HANDOFF.md). O frontend completo está em [`frontend/public/`](frontend/public/) e seu funcionamento está descrito no [README do frontend](frontend/README.md).

## Banco local no Windows

Este roteiro de instalação está preparado, mas a aplicação completa ainda não foi executada e validada em Windows. O ajuste do loop assíncrono para PostgreSQL está em `gateway/serve.py` e `backend/database.py`; OAuth, navegador e transcrição local ainda precisam de um teste de ponta a ponta no sistema.

Requer Python 3.11 ou superior e PostgreSQL 17. Para subir o PostgreSQL com Docker Compose:

```powershell
python -m pip install -r requiriments.txt
Copy-Item .env.example .env
notepad .env
docker compose up -d db
```

No `.env`, configure `POSTGRES_PASSWORD` e `DATABASE_URL` com a mesma senha. A porta local padrão deste projeto é `55434` para não conflitar com outros bancos PostgreSQL; se mudar `POSTGRES_PORT`, atualize também a porta em `DATABASE_URL`. Gere uma chave Fernet uma vez:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copie o resultado para `TOKEN_ENCRYPTION_KEY` no `.env`. Guarde essa chave: sem ela os tokens OAuth e os anexos criptografados salvos no banco não podem ser lidos. Não a regenere depois de importar as contas.

Carregue as três variáveis do `.env` no PowerShell, aplique o esquema e importe o registro e os arquivos de autenticação atuais:

```powershell
Get-Content .env | ForEach-Object {
    if ($_ -match '^([^#=]+)=(.*)$') { Set-Item "Env:$($matches[1])" $matches[2] }
}
python -m alembic upgrade head
python -m backend.scripts.import_legacy
```

O importador preserva as chaves atuais e deixa os arquivos JSON no disco. Ele pode ser executado novamente; conflitos interrompem a transação em vez de substituir tokens existentes.

## Iniciar e testar

No mesmo terminal, inicie o proxy:

```powershell
python -m gateway.serve
```

Em outro PowerShell, confira a conexão com o banco:

```powershell
Invoke-RestMethod http://127.0.0.1:18080/healthz
```

O client key atual continua válido após a importação. O proxy guarda cada requisição em `runs` e os eventos SSE da resposta em `run_events`; o evento terminal define `completed`, `failed` ou `incomplete`. O texto final e o uso ficam também em `runs.response_json` e `runs.usage_json` quando o backend envia esses dados.

Para criar uma credencial OAuth adicional pelo navegador e uma chave de proxy:

```powershell
python -m backend.scripts.create_auth novo-usuario
python -m backend.scripts.gen_key novo-usuario
```

Se o mesmo usuário tiver mais de uma conta OAuth, informe um `credential_id` diferente:

```powershell
python -m backend.scripts.create_auth novo-usuario conta-secundaria
python -m backend.scripts.gen_key conta-secundaria
```

Para revogar um usuário e suas contas/chaves:

```powershell
python -m backend.scripts.revoke_user novo-usuario
```

## Identidade interna do colaborador

A identidade interna usa tabelas próprias e não altera os usuários OAuth ou as chaves do proxy. Depois de aplicar `python -m alembic upgrade head`, o operador cria a empresa, seus departamentos e as contas internas por comandos locais:

```powershell
python -m backend.scripts.provision organization EMPRESA "Minha Empresa"
python -m backend.scripts.provision department EMPRESA CONTABIL "Contabilidade"
python -m backend.scripts.provision employee EMPRESA COLAB001 --department CONTABIL
python -m backend.scripts.provision employee EMPRESA GOV001 --role governance
```

O comando de criação imprime uma senha temporária uma vez. Entregue-a ao colaborador por um canal interno apropriado. Para recuperar o acesso ou desativar uma conta, use:

```powershell
python -m backend.scripts.provision reset-password COLAB001
python -m backend.scripts.provision disable COLAB001
```

Para carregar a lista inicial de departamentos e colaboradores da planilha da Castelo Branco em um banco sem organizações, aplique as migrações e execute:

```powershell
python -m backend.scripts.import_directory "Códigos dos departamentos.xlsx"
```

O importador valida toda a planilha antes de escrever, cria a organização `CASTELO`, os departamentos e os colaboradores em uma transação e grava as senhas temporárias em `.tmp/senhas-colaboradores.csv`. Entregue cada senha por um canal interno e guarde esse arquivo fora de qualquer pasta pública. O banco guarda códigos e departamentos, sem os nomes da planilha. O importador recusa um banco que já tenha uma organização e não substitui contas existentes.

O login interno fica em `POST /api/auth/login`, com JSON `{"employee_code":"COLAB001","password":"..."}`. `GET /api/auth/me` informa a conta e se a senha precisa ser trocada; `POST /api/auth/change-password` recebe `current_password` e `new_password`; `POST /api/auth/logout` encerra a sessão. As rotas que alteram estado exigem o cabeçalho `Origin` correspondente à origem do serviço. A sessão usa cookie opaco `HttpOnly`, `Secure` e `SameSite=Lax`, dura até oito horas e pode ser revogada no banco. Cinco tentativas de senha inválida bloqueiam a conta por 15 minutos; o operador também pode recuperar o acesso com `reset-password`. A senha nova precisa ter pelo menos 12 caracteres. O navegador precisa acessar o serviço por HTTPS para usar o cookie seguro; a configuração HTTPS entra na etapa de infraestrutura.

## OAuth compartilhado

Após a migração, o operador cria a credencial sem token e designa o colaborador que fará a conexão. Depois pode atribuí-la a outras contas internas. Os códigos de colaborador continuam separados do ID do dono OAuth:

```powershell
python -m backend.scripts.shared_oauth create DONO_OAUTH CONTA01 COLAB001 --rpm 60 --daily 500
python -m backend.scripts.shared_oauth assign CONTA01 COLAB002
python -m backend.scripts.shared_oauth unassign CONTA01 COLAB002
python -m backend.scripts.shared_oauth connector CONTA01 COLAB003
```

O comando `connector` também designa o responsável por uma credencial OAuth já importada. Com a senha interna definitiva e sessão ativa, esse responsável consulta `GET /api/oauth/credentials` e chama `POST /api/oauth/credentials/CONTA01/start` com `Origin` da aplicação. A resposta traz `connection_id` e `authorize_url`; a interface abre a URL no navegador. O OAuth Codex atual redireciona para `http://localhost:1455/auth/callback`. Após o redirecionamento, a interface pede ao responsável que cole a URL completa, mesmo que a página local não abra, e envia `{"callback_url":"..."}` a `POST /api/oauth/connections/CONNECTION_ID/complete`. O estado expira em dez minutos e só pode ser usado uma vez pela mesma sessão. Para renovar a conexão, inicie outro fluxo; uma conta OAuth diferente da já vinculada é recusada.

O cliente pode usar `GET /api/oauth/credentials` para apresentar as credenciais atribuídas. A rota de baixo nível `POST /api/credentials/CONTA01/v1/responses` continua disponível com cookie interno e `Origin` da aplicação; o chat da fase 3 usa a API descrita abaixo. As rotas antigas `/v1/*` e suas chaves continuam disponíveis, com runs sem colaborador interno.

## Chat e histórico

Depois de `python -m alembic upgrade head`, o colaborador com senha definitiva e credencial OAuth atribuída envia uma mensagem por `POST /api/chat/messages`. A requisição usa o cookie interno e o `Origin` da aplicação:

```json
{
  "client_message_id": "e557feef-058e-45d5-9579-8251a2cc9fb9",
  "credential_id": "CONTA01",
  "model": "gpt-6-luna",
  "text": "Olá",
  "new_conversation": true
}
```

A resposta repassa os eventos SSE do Codex e inclui `X-Conversation-ID` e `X-Run-ID`. `new_conversation: true` cria uma conversa no primeiro envio; as mensagens seguintes informam `conversation_id`. Para cada envio, o backend reconstrói o contexto a partir das respostas completas daquela conversa e grava o prompt, a resposta e os eventos no PostgreSQL. Mensagens de colaboradores que compartilham uma credencial permanecem em conversas distintas. O identificador `client_message_id` pertence a uma mensagem: repeti-lo depois de uma admissão retorna `409 duplicate_message` sem novo envio ao upstream.

Se o token exigir reconexão antes da admissão, a API retorna `409` com `code: reconnect_required` e o mesmo `client_message_id`. O navegador mantém o texto, conclui o fluxo em `/api/oauth` e reenvia a mensagem uma vez com o mesmo UUID. Depois que um run é admitido, o backend nunca o reenvia automaticamente, inclusive se a conexão com o upstream falhar e a entrega ficar incerta. A interface também não repete automaticamente uma entrega incerta.

`GET /api/chat/conversations?q=...` lista e busca as conversas da própria conta por título ou conteúdo, com trecho e `match_run_id` para salto. `GET /api/chat/history?conversation_id=ID&limit=50&before=RUN_ID` pagina suas mensagens. `PATCH /api/chat/conversations/ID` altera o título. `POST /api/chat/conversations/ID/suggest-title` faz uma chamada curta adicional à IA após a primeira resposta completa; ela conta na cota e é registrada na auditoria. `DELETE /api/chat/conversations/ID` oculta a conversa do colaborador e da busca, preservando os runs para a governança até a retenção de 90 dias. A rota antiga `PATCH /api/chat/conversation` continua disponível para clientes existentes. `GET /api/chat/runs/RUN_ID` traz o prompt, a resposta completa disponível e os eventos capturados. O responsável pela governança usa `GET /api/governance/runs` para listar metadados e `GET /api/governance/runs/RUN_ID` para ler um run completo; cada leitura completa grava uma entrada em `governance_access` antes de responder. Runs antigos sem colaborador continuam fora do histórico individual e disponíveis à governança. O chat aceita anexos de até 50 MB por mensagem. Depois da migração `0010_chat_attachment_downloads`, o PostgreSQL guarda seu conteúdo criptografado, associado ao run. O colaborador dono da conversa baixa o original por `GET /api/chat/attachments/ID`; a rota retorna 404 para outras contas e para conversas excluídas. Os arquivos saem com os runs na retenção de 90 dias. Anexos anteriores à migração permanecem apenas como metadados, sem download possível.

Após a migração `0012_chat_projects`, `GET/POST /api/chat/projects` lista e cria projetos do colaborador; `PATCH/DELETE /api/chat/projects/ID` renomeia ou exclui. `PATCH /api/chat/conversations/ID/project` recebe `{"project_id":"UUID"}` ou `null` para mover o chat. `GET /api/chat/conversations` aceita `project_id=UUID` ou `unassigned=true`; a interface faz a busca global `q` sem esses filtros. Para iniciar uma conversa no projeto, `POST /api/chat/messages` recebe `project_id` junto de `new_conversation=true`. Excluir um projeto move seus chats para a lista sem projeto, preservando o histórico e a auditoria. Notas de contexto do projeto entram nas mensagens seguintes dos chats vinculados a ele.

As migrações `0013_chat_context` a `0015_seed_user_profile` acrescentam notas privadas por perfil, projeto e conversa, além de um perfil em texto único por colaborador. `GET/PATCH /api/chat/profile` consulta ou edita esse texto. `GET/POST /api/chat/context` e `PATCH/DELETE /api/chat/context/ID` gerenciam as notas. O chat inclui o perfil e as notas aplicáveis no prompt. Após uma resposta concluída, o frontend chama `POST /api/chat/runs/RUN_ID/learn` para revisar o perfil com outra chamada à IA. Edições manuais do perfil prevalecem sobre revisões automáticas iniciadas antes delas. As memórias automáticas pessoais criadas no formato anterior foram copiadas para o texto inicial sem apagar as notas originais.

Após uma resposta completa, `POST /api/chat/runs/RUN_ID/artifacts` com `{"format":"pdf"}` cria um PDF do texto da IA. `csv` e `xlsx` fazem uma chamada adicional à IA para organizar o pedido e a resposta em uma tabela JSON; essa chamada consome cota e gera um run auditável. A rota retorna o identificador do arquivo, que aparece também em `GET /api/chat/history` e pode ser baixado por `GET /api/chat/artifacts/ID`. A migração `0011_chat_artifacts` guarda o conteúdo criptografado e vinculado ao run original. Repetir a criação do mesmo formato retorna o arquivo existente. O download exige a conta dona da conversa e deixa de funcionar após exclusão da conversa ou retenção de 90 dias. Cada arquivo tem limite de 20 MB.

O prompt do chat informa à IA que o Maximus gera arquivos. Quando o usuário pede explicitamente conteúdo em PDF, o frontend chama a rota de criação após a resposta completa e exibe o cartão do arquivo. Perguntas apenas sobre a capacidade recebem orientação para usar **Criar arquivo**, sem produzir um PDF vazio. Respostas antigas não são reescritas; um PDF pode ser criado pelo menu sob uma resposta já existente.

`GET /api/chat/artifacts/ID/preview` usa a mesma autorização. Para PDF, devolve o arquivo com disposição `inline`; para CSV e XLSX, devolve JSON com cabeçalhos e até 100 linhas, além do indicador `truncated`. A interface mostra essa prévia em uma janela e mantém o download integral disponível.

`GET /api/chat/attachments/ID/preview` aplica a autorização do download. Devolve PDF e imagens para exibição no navegador, tabelas CSV/TSV/XLSX como JSON e texto/código como JSON limitado a 200 KB. Formatos sem prévia retornam 415; o arquivo original continua disponível para download.

Uma conta `collaborator` pode receber `employees.can_govern = true` por uma operação administrativa no banco e acessar a governança sem perder o chat. A permissão é conferida em cada requisição; a interface mostra Governança na barra lateral e no menu de perfil dessa conta. Contas sem a permissão continuam recebendo `403` nas rotas de governança.

## Análise e alertas da fase 4

O backend analisa a mensagem nova antes de encaminhá-la. O chat e as rotas de proxy usam o mesmo ponto de admissão. A análise registra achados sem bloquear a mensagem. As regras atuais marcam cabeçalhos de chave privada PEM como alta confiança; padrões de CPF, CNPJ e pedidos explícitos para ignorar instruções ficam para revisão. Os achados guardam categoria, regra e confiança, sem copiar trechos do prompt.

O responsável pela governança consulta metadados em `GET /api/governance/findings` e o estado das notificações em `GET /api/governance/alerts`. Ambas as rotas aceitam `limit` e `before` para paginação. `GET /api/governance/runs/RUN_ID/export` baixa o conteúdo bruto em JSON e registra `action=export` em `governance_access`. A leitura normal do run continua registrando `action=read`.

Cada achado de alta confiança cria um alerta pendente na mesma transação do run. O processo de envio usa SMTP com TLS implícito e precisa destas variáveis protegidas: `GOVERNANCE_ALERT_EMAIL`, `ALERT_SMTP_HOST`, `ALERT_SMTP_FROM` e, se o servidor exigir login, `ALERT_SMTP_USERNAME` e `ALERT_SMTP_PASSWORD`. `ALERT_SMTP_PORT` usa 465 por padrão. Depois de configurar as variáveis no ambiente do serviço, execute o processo separado:

```bash
.venv/bin/python -m backend.scripts.deliver_alerts --loop
```

Sem `--loop`, o comando processa um alerta pendente e termina. O processo contínuo consulta a fila a cada cinco segundos quando ela está vazia. Falhas de SMTP deixam o alerta no PostgreSQL e programam outra tentativa; o chat não aguarda o e-mail. O e-mail contém somente a categoria e a rota protegida do run. Uma queda após a aceitação pelo SMTP e antes do registro de sucesso pode causar um envio repetido. A remoção dos dados brutos e dos achados após 90 dias pertence à fase 5.

## Request de Responses

O backend exige `input` como lista e `stream: true`:

```json
{
  "model": "gpt-6-luna",
  "input": [{"role": "user", "content": "ping"}],
  "store": false,
  "stream": true
}
```

## Dados e segurança

- `TOKEN_ENCRYPTION_KEY` criptografa os tokens OAuth antes de gravá-los no PostgreSQL.
- As chaves de cliente são guardadas somente como hashes.
- Os prompts e dados completos dos eventos de resposta ficam no banco por até 90 dias. Agende diariamente `python -m backend.scripts.retain` com `DATABASE_URL` configurada. O comando consolida métricas diárias antes de apagar runs vencidos, eventos, achados e alertas associados na mesma transação; repeti-lo não duplica métricas. Agregados expiram após 12 meses. O agendamento e seus logs pertencem à infraestrutura de implantação.
- A governança consulta `GET /api/governance/reports/daily?start=AAAA-MM-DD&end=AAAA-MM-DD` e exporta o mesmo JSON em `/api/governance/reports/daily/export`. O relatório combina dados recentes com agregados arquivados e não contém identidade de colaborador.
- A migração `0006_retention_aggregates` remove cópias de turnos anteriores das requisições de chat já armazenadas; novos runs também guardam só o turno corrente, enquanto o contexto completo continua sendo enviado ao upstream. Faça backup antes de aplicar essa migração em qualquer base persistente.
- `.env`, os registros JSON locais e os arquivos OAuth locais são ignorados pelo Git.
- O login OAuth continua ocorrendo no navegador; os tokens importados e os novos ficam associados ao `user_id` informado.

## QA supervisionado com AEC

Instale o AEC fixado em `requiriments.txt` no ambiente do projeto:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requiriments.txt
.venv/bin/python -c "import aec; print(aec.__file__)"
.venv/bin/aec --help
```

O comando `scan` usa o Codex CLI para um QA inicial em modo somente leitura. Ele só chama o implementador quando o QA relata um defeito reproduzido de lógica ou eficiência em um módulo Python existente. O ciclo adversarial usa worktrees separadas e a suíte existente como quality gate. Os testes de banco precisam de um PostgreSQL descartável com as migrações aplicadas. Em um terminal, inicie o banco:

```bash
docker run --rm --name harnesscastelo-aec-pg -e POSTGRES_PASSWORD=test -p 127.0.0.1:55433:5432 postgres:17-alpine
```

Em outro terminal, prepare o esquema e inicie o run:

```bash
export DATABASE_URL=postgresql+psycopg://postgres:test@127.0.0.1:55433/postgres
.venv/bin/python -m alembic upgrade head
export HARNESS_TEST_DATABASE_URL="$DATABASE_URL"
.venv/bin/python tools/aec_cycle.py scan
```

O comando imprime `run_id`, `status` e o caminho do SQLite. Se o QA não encontrar correção necessária e os testes passarem, o estado será `NO_CHANGES`; uma falha no gate mantém o run em `NEEDS_REVIEW`. Uma correção que passar pela revisão e pelos testes para em `WAITING_APPROVAL`. Substitua `RUN_ID` pelo valor impresso para consultar o scan, a revisão, os gates e a aprovação pendente:

```bash
.venv/bin/python tools/aec_cycle.py report RUN_ID
.venv/bin/aec --database .audit/aec/RUN_ID/aec.sqlite approvals pending
```

Cada run usa um SQLite próprio em `.audit/aec/RUN_ID/aec.sqlite`. O script copia os arquivos rastreados e os testes locais para um repositório temporário dentro de `.audit`, preservando o diretório de trabalho principal. O AEC cria worktrees distintas para o scan, a implementação e a revisão. O comando não decide a aprovação, não faz merge e não publica metodologias. Os arquivos do run permanecem em `.audit` para inspeção; o PostgreSQL descartável guarda somente os dados criados pelos testes.

Para repetir o ensaio determinístico sem turnos Codex, use `.venv/bin/python tools/aec_cycle.py start` com outro banco de testes descartável.
