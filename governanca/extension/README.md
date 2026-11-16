# Extensão HarnessCastelo

A extensão aplica a política de envio e captura prompts e respostas observados no ChatGPT e no Claude. O conteúdo, o colaborador, o departamento e os metadados de contexto são enviados à API da Governança; arquivos são registrados somente por metadados observáveis.

## Desenvolvimento local

1. Em `chrome://extensions`, carregue a pasta `governanca/extension/` como extensão descompactada. A API configurada precisa estar acessível.
2. Entre pelo popup com a conta do colaborador. A senha temporária abre a página de troca de senha do servidor da Governança; depois entre novamente. A extensão vincula a instalação autenticada à conta automaticamente.
3. Leia e confirme o aviso de privacidade. Com a conta autenticada e o aviso vigente, a captura é ativada automaticamente; você pode pausá-la pelo popup.

Esta cópia aponta para `https://governanca.castelotecnologia.com.br`; após atualizar a extensão, clique em “Recarregar” em `chrome://extensions` e atualize as abas do ChatGPT e do Claude. Preserve a chave pública do manifesto, que mantém o ID autorizado pelo servidor. A sessão renova automaticamente enquanto houver uso; após 90 dias sem uso, será necessário entrar novamente.

No ChatGPT, a extensão também registra metadados técnicos do stream. No Claude, a conclusão da resposta é estimada quando o texto renderizado fica estável e o controle de interrupção some. A captura reflete o conteúdo observável no navegador e não comprova que o provedor recebeu ou processou todos os dados.
