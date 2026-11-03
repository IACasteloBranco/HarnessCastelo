# Servidor de Governança

Este diretório contém a API própria da extensão em `app.py`, as rotas de autenticação em `auth_api.py`, a inspeção local em `data_protection.py` e o adaptador do Google Sensitive Data Protection em `sensitive_data_protection.py`. Inicie o serviço com `python -m governanca.server.app`; ele não inicia o proxy do Codex.

A rota de inspeção combina a validação local de CPF/CNPJ com os detectores `BRAZIL_CPF_NUMBER`, `EMAIL_ADDRESS` e `PHONE_NUMBER` do Google. CNPJ continua local porque o Google não oferece um infoType de CNPJ. O texto segue para o endpoint regional `southamerica-east1`; configure `SENSITIVE_DATA_PROTECTION_PROJECT_ID` e, se necessário, `SENSITIVE_DATA_PROTECTION_LOCATION`. O SDK usa Application Default Credentials do servidor, sem chave na extensão.

Ative a API Sensitive Data Protection no projeto e conceda à identidade de serviço do novo servidor apenas o papel `roles/dlp.user`. A rota falha de modo fechado (HTTP 503) se a inspeção obrigatória não puder ser concluída. A chamada usa `include_quote=false`; não há registro local do texto nem dos trechos encontrados.

A extensão continua usando os caminhos `/api/auth/extension/*`, `/api/capture/*` e `/healthz`. Configure `governanca/extension/src/background/config.js` com a URL pública deste serviço quando a implantação estiver pronta. O serviço reutiliza a autenticação Harness e o banco de identidade existentes; ele não encaminha prompts para o Codex.
