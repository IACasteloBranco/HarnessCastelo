# Servidor de Governança

Este diretório contém a API própria da extensão em `app.py`, a composição das rotas compartilhadas de identidade e da inspeção em `auth_api.py`, a inspeção local em `data_protection.py` e o adaptador do Google Sensitive Data Protection em `sensitive_data_protection.py`. Inicie o serviço com `python -m governanca.server.app`; ele não inicia nem importa o proxy do Codex.

A rota valida CPF e CNPJ localmente. O Google também inspeciona CPF, e-mail, telefone, nomes e características potencialmente sensíveis.

Antes de gravar uma interação ou resposta, a API inspeciona o texto novamente e salva a versão protegida. Se o SDP falhar, a API retorna HTTP 503 e não grava o conteúdo. O endpoint de captura não aceita conteúdo sem um inspetor configurado.

As características incluem idade, gênero, etnia, estado civil, orientação sexual, saúde, emprego, imigração, religião e política. O SDP eleva a confiança de detecções próximas a termos como “cliente”, “perfil”, “cadastro” ou “paciente”. Esses infoTypes exigem confiança `LIKELY` ou maior.

A política de mascaramento continua separada da detecção e tem versão `governanca-2`. CNPJ continua local porque o Google não oferece um infoType de CNPJ. O texto segue para `southamerica-east1`. Configure `SENSITIVE_DATA_PROTECTION_PROJECT_ID` e, se necessário, `SENSITIVE_DATA_PROTECTION_LOCATION`. O SDK usa Application Default Credentials do servidor, sem chave na extensão.

Ative a API Sensitive Data Protection no projeto e conceda à identidade de serviço do novo servidor apenas o papel `roles/dlp.user`. A rota falha de modo fechado (HTTP 503) se a inspeção obrigatória não puder ser concluída. A chamada usa `include_quote=false`; não há registro local do texto nem dos trechos encontrados.

A regra de contexto usa infoTypes e hotwords da API Sensitive Data Protection. Consulte [regras para ajustar detectores](https://cloud.google.com/sensitive-data-protection/docs/creating-custom-infotypes-rules), [ajuste de confiança por hotword](https://cloud.google.com/sensitive-data-protection/docs/creating-custom-infotypes-likelihood) e o [catálogo de infoTypes](https://cloud.google.com/sensitive-data-protection/docs/infotypes-reference). O SDP verifica categorias documentadas e termos próximos; ele não infere todo perfil ou significado da conversa. Os marcadores são pseudonimização reversível e não tornam o restante do texto anônimo.

O Google informa que a quantidade e o tipo de infoTypes afetam a latência e que `PERSON_NAME` pode aumentar bastante o tempo de inspeção. Como o envio depende dessa inspeção, uma chamada acima do limite configurado continua falhando de modo fechado.

A extensão continua usando os caminhos `/api/auth/extension/*`, `/api/capture/*` e `/healthz`. Configure `governanca/extension/src/background/config.js` com a URL pública deste serviço quando a implantação estiver pronta. O serviço reutiliza os contratos de autenticação e os modelos PostgreSQL de `shared/identity`; as migrações ficam em `shared/migrations`. Ele não encaminha prompts para o Codex.
