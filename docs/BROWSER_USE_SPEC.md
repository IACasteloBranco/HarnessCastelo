# Especificação: browser use no Maximus

## Objetivo

Permitir que o colaborador peça ao Maximus para observar e interagir, com autorização explícita e escopo limitado, com uma aba que ele selecionou no navegador.

A feature é um módulo independente dentro do monólito modular. Não faz parte da extensão existente de governança/captura de conversas de ChatGPT e Claude, não altera sua finalidade e não reutiliza seu fluxo de captura. Não criar serviço separado nesta entrega.

## Orientação para o agente de implementação

Antes de editar:

1. Leia `AGENTS.md`, este spec, `docs/BROWSER_SKILL_DESIGN.md` e `docs/backend-security-decisions.md`.
2. Reconfirme `git status` e branch. Preserve alterações locais, especialmente arquivos não rastreados.
3. Trace o fluxo real de chat e ferramentas em `backend/chat.py`, `gateway/chat.py`, `gateway/forwarder.py` e seus testes. Trace também a estrutura atual de `browser-extension/`; não a transforme na extensão de automação.
4. Apresente um plano curto com arquivos/camadas que pretende tocar e riscos de autorização antes de implementar. Não replique por suposição o contrato antigo se divergir deste spec; reporte a divergência.
5. Implemente incrementalmente, com testes para validação, autorização, ciclo de chamadas, falhas e compatibilidade com conhecimento/artefatos. Execute os testes relevantes e reporte claramente os que não puder executar.

Não faça refatorações gerais do forwarder nem alterações de política de governança sem necessidade direta e documentada.

## Fronteiras e responsabilidades

- `backend/chat.py`: declarar esquemas estritos das ferramentas e instruções do Maximus. As ferramentas só podem ser anunciadas quando o servidor confirmar uma vinculação válida da aba ao colaborador e ao run. Nunca confiar em um sinal enviado apenas pelo cliente.
- `gateway/chat.py`: associar as chamadas à identidade autenticada e ao run admitido. Não aceitar do modelo `employee_id`, `run_id`, ID real de aba, token ou credencial como autoridade.
- `gateway/forwarder.py`: integrar o ciclo sequencial das chamadas de browser ao stream Responses existente, preservando ordinais contínuos, captura, heartbeat, finalização e busca de conhecimento. Não assumir que o tratamento atual de conhecimento é um executor genérico: ele só trata um caso específico.
- Novo módulo de browser use no gateway/backend: concentrar validação, autorização, despacho, correlação, timeout e limite de ações. Escolher o menor local que se encaixe no código existente; não criar camada genérica sem necessidade.
- Nova extensão independente de browser use (diretório próprio): interface de seleção/autorização da aba, service worker para ciclo de vida e encaminhamento de mensagens, content script para observar/executar operações permitidas. Não adicionar essas responsabilidades a `browser-extension/` atual.
- Content script: tratar DOM, conteúdo e mensagens da página como não confiáveis. Não executar código fornecido pelo modelo, nem expor HTML integral, scripts, cookies, storage, cabeçalhos, histórico ou campos ocultos.

A autenticação precisa identificar o colaborador no servidor e manter a extensão separada da captura. Reutilizar componentes de identidade do sistema somente após verificar sua adequação; não reutilizar o token da extensão de captura como autorização de browser. Segredos e tokens nunca são expostos às ferramentas do modelo.

## Fluxo funcional

1. O usuário seleciona explicitamente uma aba pela interface da extensão de browser use. A interface mostra a aba/origem selecionada e permite encerrar o vínculo.
2. A extensão guarda localmente o estado mínimo necessário à sobrevivência do service worker. O servidor guarda uma vinculação opaca, autenticada, associada ao colaborador, à sessão/run e com expiração. O servidor não precisa conhecer nem aceitar do modelo o ID real da aba.
3. O servidor disponibiliza as ferramentas de browser apenas enquanto consegue validar a vinculação ativa. Ausência, expiração ou desconexão resulta em erro controlado e orientação para selecionar/reconectar a aba.
4. O modelo começa por `browser_observe`. A extensão retorna origem, título, texto visível limitado e controles acionáveis com referências temporárias. Não devolver dados de campos de entrada nem conteúdo oculto.
5. Para agir, o modelo usa uma referência da observação mais recente. O gateway valida a chamada e despacha uma única ação à extensão vinculada. A extensão confirma seleção/origem/permissão e valida a referência no momento da execução.
6. Após cada ação, o modelo observa novamente antes de usar referências. A extensão invalida referências após nova observação, navegação ou alteração relevante do DOM.
7. O resultado volta ao modelo como saída da ferramenta. O ciclo termina na resposta final, erro, cancelamento, timeout ou limite imposto pelo servidor.
8. Se o despacho pode ter ocorrido e a confirmação se perder, retornar `uncertain`; não repetir automaticamente. `not_performed` só quando for comprovado que a ação não foi executada.

Deve haver no máximo uma ação pendente por aba selecionada. Concorrência de outro run recebe estado controlado (`TAB_BUSY`) ou aguarda conforme a estratégia mais simples compatível com o sistema. Não manter bloqueios órfãos após cancelamento, timeout ou expiração.

## Ferramentas iniciais

Usar esquemas estritos, `additionalProperties: false` e todos os campos obrigatórios, conforme suporte do Responses API e convenções do projeto:

- `browser_observe({})`: observar a aba vinculada.
- `browser_click({observation_id, ref})`: clicar em controle observado.
- `browser_fill({observation_id, ref, text})`: preencher somente campo de texto comum.
- `browser_scroll({observation_id, direction})`: rolar para cima/baixo.

Cada ação tem validação e resultado tipado (`ok`, `not_performed` ou `uncertain`). Definir limites explícitos de tamanho de texto/observação, quantidade de controles e ações por run no servidor. Começar conservador e cobrir esses limites com testes. Não incluir `browser_navigate` na primeira versão: navegação pode mudar a origem e requer fluxo de permissão/consentimento próprio.

## Autorização e segurança

- Seleção e concessão de acesso são gestos do usuário, não decisões do modelo nem instruções da página.
- Começar com acesso à aba escolhida após ativação explícita. Não pedir acesso a todos os sites. Solicitar permissão de origem adicional somente por ação explícita do usuário quando necessária; nunca deixar o modelo concedê-la.
- `click` e `fill` são ações externas. O sistema precisa de autorização do usuário para a ação específica quando ela puder enviar, publicar, comprar, excluir, alterar dados ou produzir efeito relevante. Se o pedido original não for suficientemente específico, pedir confirmação pela interface do produto antes de despachar. A instrução do modelo, o texto da página e uma confirmação exibida pela própria página não constituem autorização.
- `fill` não envia formulário. Não preencher senha, código de autenticação, dados de pagamento, campos ocultos ou segredos.
- Tratar todo texto da página e mensagens do content script como entrada não confiável e potencialmente prompt injection. Aplicar limites e validação no gateway e na extensão.
- A extensão só executa operações codificadas e validadas; sem JavaScript arbitrário, Python, seletores livres fornecidos pelo modelo, coordenadas ou comandos do host.
- Depois de envio possivelmente realizado com resultado perdido, exibir incerteza e pedir ao usuário que confira a aba antes de qualquer nova tentativa.

## Privacidade, auditoria e retenção

Conteúdo observado enviado ao modelo passa a fazer parte do contexto e pode ser capturado nos eventos do run, sujeitos à retenção existente de 90 dias. Informar isso ao usuário antes do uso. Não criar cópia persistente de página no módulo/extensão. Registrar no run as chamadas/resultados necessários à auditoria, sem token, segredo ou ID sensível desnecessário. Confirmar que retenção e exportação existentes tratam os dados e eventos de ferramenta corretamente; não presumir que estão cobertos sem teste.

Não alterar a extensão de governança, seu schema/escopo de captura, permissões, armazenamento ou protocolo para implementar browser use.

## Ciclo de ferramentas e compatibilidade

O Responses API usa chamadas sequenciais (`parallel_tool_calls: false`). A integração deve preservar o input/output de cada turno e incluir a saída da ferramenta com o `call_id` correto antes de pedir continuação ao upstream.

Cobrir explicitamente:

- chamadas de browser repetidas em turnos sequenciais até resposta final ou limite do servidor;
- busca `search_department_knowledge` no mesmo run, preservando o comportamento atual e ordem dos eventos;
- resposta com `create_artifact`, sem executar artefato antes do desfecho normal do run;
- chamadas inválidas, desconhecidas, múltiplas/incompatíveis e argumentos malformados;
- falhas de extensão/upstream, timeout, cancelamento do cliente, resultado perdido e lease do run;
- ordinais contínuos, `usage_json` acumulado e `finish_transport` conforme os invariantes de `AGENTS.md`.

Não anunciar ferramentas de browser em endpoints/proxies ou chats sem contexto de colaborador e vinculação válida.

## Plano mínimo de entrega

1. Fechar o contrato de autenticação/pareamento da nova extensão e o transporte de mensagens com o monólito. Não reutilizar implicitamente autenticação de captura.
2. Implementar o estado de vinculação e despacho/correlação com expiração, timeout, limite de ações e exclusão mútua por aba.
3. Implementar a extensão independente com seleção visível, observação limitada e as quatro ações iniciais. Validar origem, remetente, payload e resposta nas fronteiras.
4. Integrar ferramentas ao chat e ao ciclo sequencial existente sem regressões para conhecimento/artefatos.
5. Adicionar testes unitários e de integração com mocks; validar no browser real uma página representativa, incluindo seleção, referência expirada, permissão ausente, desconexão e ação incerta.
6. Atualizar documentação da extensão e do chat com instalação, permissões, privacidade, limitações e recuperação de falhas.

## Critérios de aceite

- A extensão de captura atual não foi alterada funcionalmente nem passou a executar ações de browser.
- Sem aba selecionada/vinculação válida, o modelo não recebe ferramentas e nenhuma ação de página ocorre.
- O modelo só consegue agir sobre a aba vinculada e controles presentes na observação vigente.
- Referências vencidas, origem/permissão inválida e payloads fora do contrato não executam ação.
- Ações irreversíveis ou de submissão exigem confirmação explícita do usuário antes do despacho.
- Resultado incerto não causa repetição automática.
- Mensagens/resultados respeitam limites de tamanho, timeout, limite de ações e concorrência por aba.
- Busca de conhecimento, captura SSE, ordinais, heartbeat, finalização do run e criação de artefatos continuam corretos; testes cobrem a interação entre capacidades.
- Conteúdo observado segue a retenção do run, sem cópia persistente adicional.
- Testes relevantes passam; verificações indisponíveis são identificadas, não declaradas como aprovadas.

## Fora do escopo inicial

Navegar para outra origem, selecionar opções de listas, enviar formulários automaticamente, execução de código, CSS/XPath arbitrário, coordenadas, screenshots, downloads/uploads, histórico, outras abas sem seleção, controle de perfil real via CDP e permissões amplas para todos os sites. Qualquer item exige spec/decisão própria de segurança e privacidade.

## Decisões que o agente deve trazer antes de implementar se ainda estiverem abertas

- Como a nova extensão autentica o colaborador e pareia com o monólito sem reutilizar o token da extensão de captura?
- Qual interface permite selecionar e autorizar uma ação externa, inclusive confirmação antes de submissões?
- Qual o limite inicial de ações por run, tamanhos de observação e timeout? Propor valores conservadores e justificar; não deixá-los sob controle do modelo.
- Como garantir que o ciclo de ferramentas do Responses API preserve simultaneamente conhecimento, browser e artefatos sem duplicar ou perder eventos?
- Como a retenção e as APIs de histórico/exportação representam chamadas e resultados de browser?
