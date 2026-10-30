# Frontend do Maximus AI

As [etapas 1 a 4 do roadmap](../docs/FRONTEND_ROADMAP.md) cobrem entrada, conexão OAuth, chat do colaborador, console de governança e várias conversas com busca. O chat usa `gpt-6-luna`, conforme o contrato documentado no [README principal](../README.md). Cada colaborador vê somente as próprias conversas. Depois da primeira resposta, uma chamada adicional à IA sugere um título curto, que pode ser editado na barra lateral. A exclusão tira a conversa da interface e da busca, preservando a auditoria pelo prazo de retenção. Quem tem permissão adicional de governança alterna entre chat e console; o conteúdo bruto de uma execução só é carregado após selecioná-la na lista de atividade.

A governança separa visão geral, atividade e administração. Os indicadores principais mostram uso do Maximus, achados e tempo médio de resposta; a lista de atividade mostra status, horário, origem e duração. No chat, o cabeçalho indica o filtro de projetos, o campo de mensagem cresce com o texto e o contexto abre como painel lateral no desktop. Menus, navegação e painéis usam transições discretas, desativadas quando o sistema solicita movimento reduzido.

Uma conta com papel de governança também pode abrir o chat e manter conversas próprias. Para enviar mensagens no ambiente real, ela precisa receber uma credencial OAuth atribuída. Como essa conta não pertence a um departamento, a busca em documentos departamentais não aparece entre suas ferramentas de chat.

Na barra lateral, **Projetos** agrupa conversas do próprio colaborador. O botão **+** cria um projeto; clicar no nome filtra a lista sem trocar a conversa aberta. **Novo chat** cria a próxima conversa dentro do projeto selecionado após a primeira mensagem. O menu **⋯** do chat permite mover para outro projeto ou para **Sem projeto**. Projetos podem ser renomeados e excluídos; excluir devolve as conversas para **Sem projeto** sem apagar o histórico. A busca encontra conversas de todos os projetos.

O botão **Contexto** abre o perfil do colaborador e as notas do perfil, do projeto selecionado e da conversa atual. O perfil é um texto único, que o colaborador pode corrigir, substituir ou apagar. O colaborador também pode adicionar, editar e excluir notas de instrução ou memória. O menu do perfil abre diretamente o contexto pessoal; o menu do projeto abre o contexto daquele projeto. O perfil e as notas dos três níveis aplicáveis entram nas próximas mensagens enviadas à IA. O histórico de cada conversa continua separado desse contexto persistente.

Após uma resposta concluída, o Maximus faz uma chamada adicional ao modelo para revisar o texto do perfil com base no que o colaborador declarou. A revisão deve preservar fatos anteriores e atualizar preferências corrigidas pelo próprio usuário; se não houver informação pessoal durável, o texto fica igual. O processamento ignora anexos e tenta descartar segredos e dados sensíveis; como a classificação automática pode falhar, o colaborador deve revisar o perfil pelo botão **Contexto**. Uma edição manual feita durante a revisão impede que uma versão antiga a substitua. A revisão usa a cota da conta conectada e uma falha não altera a resposta já recebida. As notas continuam limitadas a 30 por nível e persistem até exclusão; apagar uma conversa ou projeto apaga apenas as notas exclusivas daquele nível.

Memórias automáticas pessoais criadas antes do perfil em texto foram copiadas para o perfil inicial pela migração `0015_seed_user_profile`. As notas originais continuam disponíveis em **Notas adicionais** para conferência e eventual exclusão.

O botão de anexo permite enviar até cinco arquivos por mensagem, com limite total de 50 MB. São aceitos PDF, imagens, documentos, planilhas, apresentações, texto e código nas extensões mostradas pelo seletor. O conteúdo é transmitido à IA no envio atual e guardado criptografado no PostgreSQL até a retenção de 90 dias. O colaborador abre o cartão no histórico para visualizar ou baixar o original; outros colaboradores não podem acessar o arquivo. Anexos enviados antes da migração `0010_chat_attachment_downloads` aparecem no histórico, mas não têm conteúdo disponível para download. TXT, PNG e PDF foram confirmados na conexão OAuth real; outros formatos dependem do suporte do endpoint Codex. Áudio e vídeo não são analisados diretamente nessa conexão. As respostas da IA são exibidas em Markdown, com HTML desativado.

A prévia de anexos mostra PDF e imagens no navegador, até 100 linhas de CSV/TSV/XLSX e os primeiros 200 KB de arquivos de texto e código. HTML e XML aparecem como texto para não executar conteúdo enviado. Formatos de escritório sem renderizador local, como DOCX, PPTX e XLS, abrem a janela com a opção de baixar o original. A prévia exige a mesma autorização do download.

O botão de áudio aceita gravação pelo microfone e arquivos MP3, MP4, MPEG, MPGA, M4A, WAV, WebM, OGG e Opus, até 25 MB e cinco minutos. Um modelo local transcreve a fala em português; o resultado entra no campo de mensagem para revisão e só chega à IA se o colaborador clicar em **Enviar**. O áudio não é retido. Antes de iniciar o servidor pela primeira vez, instale as dependências e baixe o modelo na raiz do projeto:

```bash
python -m pip install -r requiriments.txt
python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8', download_root='.tmp/transcription-models')"
```

O modelo ocupa cerca de 500 MB. A gravação exige acesso ao microfone e uma origem HTTPS ou `localhost`.

O modelo decide quando um arquivo é útil e pode criar PDF, XLSX ou CSV como parte da resposta. O PDF usa a identidade visual Maximus (logotipo, cabeçalho, rodapé e paginação) e preserva títulos, listas, citações, blocos de código e tabelas Markdown. A planilha XLSX recebe cabeçalho e cores da marca, filtro, larguras de coluna e cabeçalho congelado. O arquivo fica no histórico da conversa como cartão para download. A geração não executa código da IA nem importa arquivos de outras conversas. O arquivo criptografado é acessível apenas ao colaborador dono da conversa e sai com o run na retenção de 90 dias. A planilha deve ser conferida antes de uso contábil.

Ao clicar no cartão de um arquivo criado, o colaborador abre a prévia. O PDF aparece no navegador; CSV e XLSX aparecem em tabela com até 100 linhas. O botão **Baixar arquivo** no visualizador entrega o arquivo completo. A prévia usa a mesma verificação de acesso do download e não faz nova chamada à IA.

O chat oferece à IA a ferramenta `create_artifact`. A IA decide durante a resposta se deve criar PDF, XLSX ou CSV e prepara o conteúdo; o Maximus valida e renderiza o arquivo após a conclusão, e o cartão aparece na conversa. Perguntas apenas sobre a capacidade não devem gerar arquivo. Respostas antigas continuam como foram registradas; é possível criar um arquivo pelo menu sob a resposta desejada.

O FastAPI serve `frontend/public/` e `/api` na mesma origem. Para testar no navegador local com o cookie de sessão `Secure`, inicie o gateway por HTTPS na raiz do projeto:

```bash
mkdir -p .tmp
openssl req -x509 -newkey rsa:2048 -nodes -days 7 \
  -keyout .tmp/dev-key.pem -out .tmp/dev-cert.pem \
  -subj '/CN=localhost' -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1'
.venv/bin/python -m uvicorn gateway.main:app --host 127.0.0.1 --port 18443 \
  --ssl-keyfile .tmp/dev-key.pem --ssl-certfile .tmp/dev-cert.pem
```

Abra `https://localhost:18443/` e aceite o certificado local no navegador. Configure o banco e execute as migrações descritas no [README principal](../README.md) antes de entrar. As contas e credenciais continuam sendo criadas e atribuídas pelos comandos do operador. O responsável pela conexão abre a página de autorização em outra aba e cola a URL final de callback no Maximus AI.

O servidor HTTP existente em `127.0.0.1:18080` permanece disponível para clientes de proxy. O login no navegador requer HTTPS; em produção, use um certificado confiável e preserve a mesma origem para a interface e `/api`.

No Windows, execute pelo PowerShell com o ambiente virtual ativo. Gere primeiro o certificado local com OpenSSL e inicie o gateway:

```powershell
New-Item -ItemType Directory -Force .tmp
openssl req -x509 -newkey rsa:2048 -nodes -days 7 -keyout .tmp/dev-key.pem -out .tmp/dev-cert.pem -subj '/CN=localhost' -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1'
python -m uvicorn gateway.main:app --host 127.0.0.1 --port 18443 --ssl-keyfile .tmp/dev-key.pem --ssl-certfile .tmp/dev-cert.pem
```

Em outro PowerShell, execute `python frontend/tests/smoke.py`.
No Windows, execute pelo PowerShell com o ambiente virtual ativo. Gere primeiro o certificado local com OpenSSL e inicie o gateway:

```powershell
New-Item -ItemType Directory -Force .tmp
openssl req -x509 -newkey rsa:2048 -nodes -days 7 -keyout .tmp/dev-key.pem -out .tmp/dev-cert.pem -subj '/CN=localhost' -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1'
python -m uvicorn gateway.main:app --host 127.0.0.1 --port 18443 --ssl-keyfile .tmp/dev-key.pem --ssl-certfile .tmp/dev-cert.pem
```

Em outro PowerShell, execute `python frontend/tests/smoke.py`.

Para conferir as telas e os fluxos com respostas simuladas, instale o navegador do Playwright com `python -m playwright install chromium`, deixe o servidor HTTPS ativo e execute `python frontend/tests/smoke.py`. O teste usa o Chromium instalado pelo Playwright e salva capturas no diret?rio tempor?rio do sistema.

## Prévia local sem contas reais

Execute `python -m frontend.dev_preview` e abra `http://localhost:18444/`. Entre com `DEMOCHAT` e `demo12345` para ver o chat, ou com `DEMOGOV` e `demo12345` para ver o console. Saia da primeira conta antes de entrar na outra. A prévia usa apenas dados simulados em memória e não consulta o banco nem envia mensagens à IA. Para testar os dois acessos pelo navegador automatizado, execute `python frontend/tests/preview.py` enquanto a prévia estiver ativa.
