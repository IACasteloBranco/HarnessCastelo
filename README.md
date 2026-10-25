# HarnessCastelo

Proxy FastAPI para o backend Codex, com OAuth por conta, chaves de cliente, limites de uso e captura de execuções para o harness.

O código está separado em `backend/`, `gateway/` e `frontend/`. O mapa atual e os limites ainda pendentes estão em [`docs/PROJECT_CONTEXT.md`](docs/PROJECT_CONTEXT.md).

## Banco local no Windows

Requer Python 3.11 ou superior e PostgreSQL 17. Para subir o PostgreSQL com Docker Compose:

```powershell
python -m pip install -r requiriments.txt
Copy-Item .env.example .env
notepad .env
docker compose up -d db
```

No `.env`, configure `POSTGRES_PASSWORD` e `DATABASE_URL` com a mesma senha. Gere uma chave Fernet uma vez:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copie o resultado para `TOKEN_ENCRYPTION_KEY` no `.env`. Guarde essa chave: sem ela os tokens OAuth salvos no banco não podem ser lidos. Não a regenere depois de importar as contas.

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

## Chat e histórico da fase 3

Depois de `python -m alembic upgrade head`, o colaborador com senha definitiva e credencial OAuth atribuída envia uma mensagem por `POST /api/chat/messages`. A requisição usa o cookie interno e o `Origin` da aplicação:

```json
{
  "client_message_id": "e557feef-058e-45d5-9579-8251a2cc9fb9",
  "credential_id": "CONTA01",
  "model": "gpt-6-sol",
  "text": "Olá"
}
```

A resposta repassa os eventos SSE do Codex e inclui `X-Conversation-ID` e `X-Run-ID`. O backend mantém uma conversa por colaborador nesta fase. Para cada envio, ele reconstrói o contexto a partir das respostas completas da própria conversa e grava o prompt, a resposta e os eventos no PostgreSQL. Mensagens de colaboradores que compartilham uma credencial permanecem em conversas distintas. O identificador `client_message_id` pertence a uma mensagem: repeti-lo depois de uma admissão retorna `409 duplicate_message` sem novo envio ao upstream.

Se o token exigir reconexão antes da admissão, a API retorna `409` com `code: reconnect_required` e o mesmo `client_message_id`. O navegador deve manter o texto, concluir o fluxo em `/api/oauth` e reenviar a mensagem uma vez com o mesmo UUID. Depois que um run é admitido, o backend nunca o reenvia automaticamente, inclusive se a conexão com o upstream falhar e a entrega ficar incerta. O frontend ainda não está implementado; esse comportamento descreve o contrato que ele deve seguir.

`GET /api/chat/history?limit=50&before=RUN_ID` pagina o histórico da própria conta. `GET /api/chat/runs/RUN_ID` traz o prompt, a resposta completa disponível e os eventos capturados. O responsável pela governança usa `GET /api/governance/runs` para listar metadados e `GET /api/governance/runs/RUN_ID` para ler um run completo; cada leitura completa grava uma entrada em `governance_access` antes de responder. Runs antigos sem colaborador continuam fora do histórico individual e disponíveis à governança. O chat inicial aceita texto; anexos e múltiplas conversas na interface ficam para uma etapa posterior.

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
  "model": "gpt-6-sol",
  "input": [{"role": "user", "content": "ping"}],
  "store": false,
  "stream": true
}
```

## Dados e segurança

- `TOKEN_ENCRYPTION_KEY` criptografa os tokens OAuth antes de gravá-los no PostgreSQL.
- As chaves de cliente são guardadas somente como hashes.
- Os prompts e dados completos dos eventos de resposta ficam no banco para uso do harness. Restrinja o acesso ao banco e aplique a política de retenção adequada ao conteúdo.
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
