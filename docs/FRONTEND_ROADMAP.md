# Roadmap do frontend do Maximus AI

## Objetivo e ordem

O Maximus AI será o chat interno da Castelo Branco. O colaborador entra com a conta da empresa, usa uma credencial ChatGPT atribuída pelo operador e consulta apenas o próprio histórico. A governança recebe um espaço separado para examinar achados e produzir relatórios. A ordem aprovada é: chat, console de governança, evolução do chat e recursos avançados após o MVP.

Este roadmap cobre a interface. O provisionamento de contas e a atribuição de credenciais continuam nos comandos locais do operador. O frontend usa as APIs existentes no mesmo domínio HTTPS; a revisão do gateway vem depois.

## Direção visual

As quatro [referências visuais](visual-references/) mostram uma base azul marinho, páginas claras, dourado/bege discreto e navegação lateral. A [tela de analytics](visual-references/governance-dashboard.jpeg) orienta o console; o [fluxo de vínculo](visual-references/installation-flow.jpeg) informa a linguagem dos estados; a [marca de governança](visual-references/governance-brand.jpeg) e o [portal Castelo](visual-references/castelo-portal.jpeg) orientam a relação com a identidade da empresa. As telas e textos dessas imagens pertencem a outros fluxos e não são especificações do Maximus AI.

| Papel | Cor inicial | Uso |
| --- | --- | --- |
| Azul profundo | `#102F4A` | Navegação, cabeçalhos e ações principais |
| Azul secundário | `#244B68` | Estados ativos e superfícies de apoio |
| Bege claro | `#F3EDE1` | Fundo acolhedor e áreas de leitura |
| Branco | `#FFFFFF` | Mensagens, formulários e conteúdo |
| Dourado | `#C9A86B` | Detalhes de marca e destaques curtos |
| Cinza azulado | `#526579` | Texto secundário |

Os valores são uma proposta extraída da direção das imagens, não um manual de marca. Use texto azul sobre o bege e o branco; não use dourado como texto pequeno sobre branco. A interface deve dizer **Maximus AI** como produto e manter **Castelo Branco** como vínculo institucional. Use uma família sem serifa legível, com títulos fortes e corpo simples. Antes de fixar fonte e proporções, compare uma tela renderizada com as referências.

O chat é a tela de trabalho, com navegação lateral compacta, conversa central ampla e campo de mensagem sempre visível. O azul deve estruturar a interface; o bege suaviza a leitura. Reserve o destaque dourado para poucos pontos, como a marca e a ação principal. No celular, a navegação vira painel recolhível e o campo de mensagem continua acessível sem rolagem excessiva.

## Etapas

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

Crie entrada exclusiva para o papel `governance`. Mostre agregados por período e departamento, categorias de achados, erros e latência com `/api/governance/reports/daily`. Permita exportar o relatório agregado. Liste runs, achados e alertas sem buscar conteúdo bruto automaticamente. Abra o detalhe bruto apenas após uma ação explícita do responsável, pois cada leitura e exportação gera auditoria no backend. Não coloque conteúdo de prompts em notificações ou cartões de resumo.

**Pronto quando** um colaborador não acessa o console, o responsável consegue consultar e exportar agregados, e a leitura ou exportação de um run acontece apenas por ação explícita. Dados apagados pela retenção de 90 dias deixam de aparecer como conteúdo bruto; agregados continuam disponíveis pelo prazo do backend.

### 4. Evolução do chat após suporte da API

Adicione várias conversas, busca e navegação de histórico quando o backend oferecer seus contratos. Adicione anexos depois que a API aceitar seus metadados; registre nome, tipo e referência técnica, sem armazenar o conteúdo do arquivo no banco do produto. Refine a experiência de reconexão OAuth a partir do uso observado na primeira interface.

**Pronto quando** conversas diferentes continuam isoladas por colaborador e os metadados de arquivos seguem a política definida em `PROJECT_CONTEXT.md`. Recursos avançados e agentes permanecem após o MVP.

## Contratos e limites que guiam a implementação

- O navegador usa cookie de sessão, nunca token OAuth ou chave de proxy. Não grave prompts, respostas ou credenciais em `localStorage`.
- O frontend chama rotas relativas `/api/...` na mesma origem. O backend atual rejeita `Origin` diferente nas ações que alteram estado.
- `/api/chat/messages` transmite SSE; o cliente precisa ler eventos e tratar fragmentos de rede sem perder a mensagem parcial.
- A API atual oferece uma conversa por colaborador e exige colar a URL do callback OAuth. Melhorar esses contratos pertence à etapa posterior do gateway/backend, após observar a primeira interface.
- O relatório agregado traz contagens e latência; não invente métricas que a API ainda não fornece. A liderança recebe somente exportações agregadas preparadas pela governança.

## Validação visual

Em 25/10/2026, o conector Playwright não iniciou: falta o Chrome esperado em `/opt/google/chrome/chrome`. O navegador do Chrome DevTools está acessível; uma aba isolada abriu e gerou uma captura de tela nesta sessão. Use esse navegador para conferir renderização, interação e responsividade quando houver interface. Se o Playwright for necessário para testes automatizados, instale ou configure o navegador exigido antes de executar esses testes.
