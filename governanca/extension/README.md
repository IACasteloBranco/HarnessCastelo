# Extensão HarnessCastelo

A extensão aplica a política de envio e captura prompts e respostas observados no ChatGPT e no Claude. O conteúdo, o colaborador, o departamento e os metadados de contexto são enviados à API local da Governança; arquivos são registrados somente por metadados observáveis.

## Desenvolvimento local

1. Inicie o PostgreSQL, aplique as migrações e rode `python -m governanca.server.app` na raiz do repositório.
2. Em `chrome://extensions`, carregue a pasta `governanca/extension/` como extensão descompactada.
3. Entre pelo popup com a conta da Governança. A senha temporária abre a página de troca de senha do servidor da Governança; depois entre novamente e solicite o vínculo da instalação para aprovação.
4. Leia e confirme o aviso de privacidade, habilite a captura e recarregue as abas do ChatGPT e do Claude.

Esta cópia de desenvolvimento aponta para `http://127.0.0.1:18081`; depois de iniciar o servidor, clique em “Recarregar” em `chrome://extensions` e atualize as abas do ChatGPT e do Claude. Antes de distribuir a extensão, restaure a URL pública e a permissão de produção. Preserve a chave pública do manifesto, que mantém o ID autorizado pelo servidor. A sessão renova automaticamente enquanto houver uso; após 90 dias sem uso, será necessário entrar novamente.

No ChatGPT, a extensão também registra metadados técnicos do stream. No Claude, a conclusão da resposta é estimada quando o texto renderizado fica estável e o controle de interrupção some. A captura reflete o conteúdo observável no navegador e não comprova que o provedor recebeu ou processou todos os dados.
