# Roadmap do frontend do Maximus AI

## Objetivo e ordem

O Maximus AI será o chat interno da Castelo Branco. O colaborador entra com a conta da empresa, usa uma credencial ChatGPT atribuída pelo operador e consulta apenas o próprio histórico. A governança recebe um espaço separado para examinar achados e produzir relatórios. A ordem aprovada é: chat, console de governança, evolução do chat e recursos avançados após o MVP.

Este roadmap cobre a interface. O provisionamento de contas e a atribuição de credenciais continuam nos comandos locais do operador. O frontend usa as APIs existentes no mesmo domínio HTTPS; a revisão do gateway vem depois.

## Direção visual

As [referências visuais](visual-references/) mostram uma base azul marinho, páginas claras, dourado/bege discreto e navegação lateral. A [tela de analytics](visual-references/governance-dashboard.jpeg) orienta o console; o [fluxo de vínculo](visual-references/installation-flow.jpeg) informa a linguagem dos estados; a [marca de governança](visual-references/governance-brand.jpeg) e o [portal Castelo](visual-references/castelo-portal.jpeg) orientam a relação com a identidade da empresa. Use a [logomarca oficial](visual-references/MARCA_VERT_-_CASTELO_BRANCO.png) na interface. A [referência do login](<visual-references/Tela de Login Corporativo Maximus.png>) orienta a entrada. As telas e textos das outras imagens pertencem a outros fluxos e não são especificações do Maximus AI.

| Papel | Cor inicial | Uso |
| --- | --- | --- |
| Azul profundo | `#102F4A` | Navegação, cabeçalhos e ações principais |
| Azul secundário | `#244B68` | Estados ativos e superfícies de apoio |
| Bege claro | `#F3EDE1` | Fundo acolhedor e áreas de leitura |
| Branco | `#FFFFFF` | Mensagens, formulários e conteúdo |
| Dourado | `#C9A86B` | Detalhes de marca e destaques curtos |
| Cinza azulado | `#526579` | Texto secundário |

Os valores são uma proposta extraída da direção das imagens, não um manual de marca. Use texto azul sobre o bege e o branco; não use dourado como texto pequeno sobre branco. A interface deve dizer **Maximus AI** como produto e manter **Castelo Branco** como vínculo institucional. Use uma família sem serifa legível, com títulos fortes e corpo simples. Antes de fixar fonte e proporções, compare uma tela renderizada com as referências.

O chat segue a [referência da área de conversa](<visual-references/Interface corporativa de chat com Maximus.png>): barra lateral azul, área central clara, marca no estado vazio e campo de mensagem sempre visível. O azul estrutura a interface; o bege suaviza a leitura. A interface oferece várias conversas, busca e anexos. Assistentes, biblioteca e ferramentas aguardam seus contratos. No celular, a lista de conversas abre pelo cabeçalho.

## Etapas

As etapas 1 a 3 e a parte de conversas e anexos da etapa 4 estão implementadas em `frontend/public/`. O teste `frontend/tests/smoke.py` usa respostas simuladas da API para conferir chat, reconexão e governança em desktop e celular. TXT, PNG e PDF foram enviados com sucesso à conexão OAuth real; os demais formatos ainda precisam de validação específica.

### 0. Base visual e ambiente de revisão

Crie a estrutura do frontend, os tokens de cor, tipografia, espaçamento e estados de foco. Sirva a interface e `/api` pela mesma origem HTTPS, inclusive no ambiente de desenvolvimento. Isso é necessário para o cookie `Secure` e para a verificação de `Origin` do backend. Prepare dados simulados para iterar sem uma conta ChatGPT real.

**Pronto quando** login, chat vazio, chat com mensagens, reconexão e console puderem ser vistos em tamanhos desktop e celular; navegação por teclado, contraste e estados de carregamento forem verificados em navegador. Não tratar imagem estática ou teste de unidade como substituto da inspeção visual.

### 1. Entrada e conexão da conta

Implemente login por código de colaborador e senha, troca obrigatória da senha temporária, restauração de sessão e logout. Após entrar, consulte `/api/auth/me` e `/api/oauth/credentials`. Mostre apenas credenciais atribuídas; somente quem tem `can_connect` inicia ou renova OAuth. Para o fluxo atual, abra `authorize_url` em outra aba, mantenha a tela do Maximus AI aberta e peça a URL final de callback para concluir a conexão. Explique o passo em linguagem comum, sem mencionar CLI.

**Pronto quando** um colaborador com senha temporária não acessa o chat antes da troca; uma sessão expirada volta ao login; a conexão OAuth pode ser concluída pela interface; uma credencial compartilhada não mistura sessões internas.

### 2. Chat inicial do colaborador

Entregue uma conversa por colaborador, seleção da credencial atribuída, envio de texto e resposta em fluxo. Use `/api/chat/messages`, `/api/chat/history` e `/api/chat/runs/{run_id}`. Exiba estado de envio, resposta parcial, conclusão, erro e limite de uso. A mensagem mantém um `client_message_id` estável. Se a API responder `reconnect_required` antes da admissão, preserve texto e ID na aba, reconecte e tente uma vez. Se a API indicar mensagem duplicada, carregue o run existente. Se a entrega ao upstream for incerta, não reenvie automaticamente.

**Pronto quando** o histórico mostra só as mensagens do colaborador, o fluxo aparece sem esperar a resposta inteira, uma falha não cria uma segunda mensagem e a interface continua utilizável em celular e por teclado. O chat inicial aceita texto; anexos e várias conversas visíveis ficam para a etapa 4.

### 3. Console de governança

Crie entrada para o papel `governance` e para colaboradores com `can_govern`. Mostre agregados por período e departamento, categorias de achados, erros e latência com `/api/governance/reports/daily`. Permita exportar o relatório agregado. Liste runs, achados e alertas sem buscar conteúdo bruto automaticamente. Abra o detalhe bruto apenas após uma ação explícita do responsável, pois cada leitura e exportação gera auditoria no backend. Não coloque conteúdo de prompts em notificações ou cartões de resumo.

**Pronto quando** um colaborador sem permissão não acessa o console, o responsável consegue consultar e exportar agregados, e a leitura ou exportação de um run acontece apenas por ação explícita. Dados apagados pela retenção de 90 dias deixam de aparecer como conteúdo bruto; agregados continuam disponíveis pelo prazo do backend.

### 4. Evolução do chat

**Implementado:** várias conversas por colaborador; “Novo chat” só aparece na lista depois da primeira mensagem; busca por título, pergunta e resposta com trecho encontrado e salto para a mensagem; título curto sugerido por uma chamada adicional à IA e editável; exclusão individual com confirmação. A exclusão oculta o histórico do colaborador, mas conserva os runs para a governança até a retenção de 90 dias.

**Projetos implementados:** cada colaborador cria, renomeia e exclui projetos privados, inicia chats dentro deles e move conversas pelo menu. A exclusão de um projeto deixa seus chats em **Sem projeto**. O vínculo da conversa ao projeto seleciona as notas de contexto aplicáveis às próximas mensagens.

**Contexto implementado:** o colaborador consulta e edita um texto único de perfil e gerencia notas do perfil, projeto e conversa. O perfil e as notas privadas entram no prompt dos próximos envios. Após cada resposta concluída, uma chamada adicional à IA revisa o perfil com preferências e fatos duráveis declarados pelo colaborador; o filtro local descarta padrões sensíveis comuns. A revisão automática pode falhar ou classificar incorretamente, então a interface permite correção e exclusão do texto. Edições manuais não são sobrescritas por uma revisão iniciada antes delas. Notas de conversa saem quando a conversa é excluída; notas de projeto saem quando o projeto é excluído. Arquivos de referência persistentes por projeto ainda não foram implementados.

**Implementado nesta etapa:** até cinco anexos por mensagem, somando 50 MB, para imagens PNG/JPEG/WebP/GIF, PDF, documentos, planilhas, apresentações, texto e arquivos comuns de código. O arquivo segue à IA no pedido atual; o banco guarda nome, tipo, tamanho, SHA-256 e conteúdo criptografado para download pelo dono da conversa. Anexos enviados antes da migração `0010_chat_attachment_downloads` não podem ser recuperados. Os arquivos são excluídos com seus runs após 90 dias. As respostas da IA mostram títulos, listas, tabelas, links, citações e blocos de código em Markdown, com HTML desativado. A IA não recebe novamente os bytes de anexos em mensagens posteriores da mesma conversa.

**Arquivos criados pela IA:** respostas concluídas oferecem PDF, XLSX e CSV. O PDF contém o texto da resposta; planilhas usam uma chamada adicional à IA para estruturar os dados. Os cartões de download permanecem no histórico, com conteúdo criptografado e acesso restrito ao dono da conversa. A migração `0011_chat_artifacts` vincula os arquivos ao run original para a retenção de 90 dias. A criação dos três formatos foi verificada com a conexão OAuth real usando dados fictícios.

**Prévia implementada:** o colaborador abre PDF no navegador ou consulta até 100 linhas de CSV/XLSX em tabela, com opção de baixar o arquivo inteiro. A prévia consulta o arquivo já armazenado e aplica a mesma autorização do download.

**Prévia de anexos enviados:** ao clicar no cartão, o colaborador visualiza PDF, imagem, CSV/TSV/XLSX ou texto/código no mesmo visualizador e pode baixar o original. A janela informa quando o formato não dispõe de renderizador local. Anexos anteriores à migração de armazenamento continuam sem conteúdo para prévia.

**Pedido de PDF no chat:** a IA recebe o contexto das capacidades reais do Maximus e entrega o conteúdo quando o colaborador pede um PDF. O frontend cria o PDF da resposta concluída automaticamente e mostra o cartão, sem depender do menu manual. Perguntas sobre a capacidade não criam arquivos vazios.

**Transcrição local:** o colaborador pode selecionar um arquivo de áudio ou gravar pelo microfone. O modelo local transcreve em português e coloca o texto no campo de mensagem para revisão; o áudio não é enviado à IA nem guardado no banco. O limite é de 25 MB e cinco minutos por gravação. O endpoint Codex usado pelo Maximus recusou um WAV como `input_audio` (HTTP 400); por isso a IA recebe apenas a transcrição revisada. Outros formatos de anexos listados no seletor seguem o contrato de `input_file`, mas ainda dependem da compatibilidade do endpoint e do modelo.

**Pendente:** análise direta de áudio/vídeo pela IA, refinamento do OAuth e validação da instalação completa no Windows.

**Pronto quando** conversas diferentes continuam isoladas por colaborador e os metadados de arquivos seguem a política definida em `PROJECT_CONTEXT.md`. Recursos avançados e agentes permanecem após o MVP.

## Contratos e limites que guiam a implementação

- O navegador usa cookie de sessão, nunca token OAuth ou chave de proxy. Não grave prompts, respostas ou credenciais em `localStorage`.
- O frontend chama rotas relativas `/api/...` na mesma origem. O backend atual rejeita `Origin` diferente nas ações que alteram estado.
- `/api/chat/messages` transmite SSE; o cliente precisa ler eventos e tratar fragmentos de rede sem perder a mensagem parcial.
- A API de conversas permite selecionar, buscar, renomear e excluir uma conversa; o callback OAuth ainda exige colar a URL final.
- O relatório agregado traz contagens e latência; não invente métricas que a API ainda não fornece. A liderança recebe somente exportações agregadas preparadas pela governança.

## Validação visual

Instale o Chromium do Playwright com `python -m playwright install chromium`. Revise login, troca de senha e conexão OAuth em desktop e celular com o Playwright. Use respostas simuladas da API para conferir os estados sem uma conta ChatGPT real; valide os contratos reais com o gateway em HTTPS.
