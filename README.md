# HarnessCastelo

Proxy FastAPI para o backend Codex, com OAuth por conta, chaves de cliente, limites de uso e captura de execuções para o harness.

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
python import_legacy.py
```

O importador preserva as chaves atuais e deixa os arquivos JSON no disco. Ele pode ser executado novamente; conflitos interrompem a transação em vez de substituir tokens existentes.

## Iniciar e testar

No mesmo terminal, inicie o proxy:

```powershell
python serve.py
```

Em outro PowerShell, confira a conexão com o banco:

```powershell
Invoke-RestMethod http://127.0.0.1:18080/healthz
```

O client key atual continua válido após a importação. O proxy guarda cada requisição em `runs` e os eventos SSE da resposta em `run_events`; o evento terminal define `completed`, `failed` ou `incomplete`. O texto final e o uso ficam também em `runs.response_json` e `runs.usage_json` quando o backend envia esses dados.

Para criar uma credencial OAuth adicional pelo navegador e uma chave de proxy:

```powershell
python create_auth.py novo-usuario
python gen_key.py novo-usuario
```

Se o mesmo usuário tiver mais de uma conta OAuth, informe um `credential_id` diferente:

```powershell
python create_auth.py novo-usuario conta-secundaria
python gen_key.py conta-secundaria
```

Para revogar um usuário e suas contas/chaves:

```powershell
python revoke_user.py novo-usuario
```

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
