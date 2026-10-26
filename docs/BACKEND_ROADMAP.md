# Roadmap do backend

## Objetivo

Entregar o backend do primeiro release do HarnessCastelo em etapas verificáveis. O proxy atual continua atendendo clientes existentes durante as migrações. O frontend, o Redis e a infraestrutura de produção ficam fora deste roadmap.

## Regras que orientam as etapas

- A identidade interna do colaborador é independente da conta OAuth.
- Uma credencial OAuth pode pertencer a vários colaboradores. Cada conversa e execução pertence a um colaborador.
- RPM e limite diário são compartilhados por credencial OAuth.
- PostgreSQL é a fonte persistente de verdade. Redis fica para depois do MVP.
- O gateway observa e registra. Ele não bloqueia mensagens no primeiro release.
- O sistema guarda prompts e respostas por 90 dias. Mantém métricas agregadas sem identificação por 12 meses depois da exclusão do conteúdo bruto.
- Evidências de achados que possam repetir trechos do prompt expiram junto com o conteúdo bruto; somente agregados sem identificação permanecem.
- Só o colaborador dono e uma conta de governança autorizada podem ler conteúdo bruto. Leituras e exportações da governança geram auditoria.
- Todos os achados ficam no banco. Regras locais marcadas como alta confiança podem gerar e-mail, sem incluir o prompt.
- Cada etapa inclui migração, código, testes e uma verificação AEC antes de seguir.

## Etapas

### 1. Identidade interna e provisionamento

Crie a estrutura da empresa única, departamentos, colaboradores, papéis e credenciais internas. O código do colaborador identifica a conta. A senha é própria, temporária no provisionamento e trocada no primeiro login. O operador provisiona e recupera contas por comandos locais.

Inclua endpoints REST JSON para login, sessão atual, troca obrigatória de senha e logout. Mantenha a sessão em cookie opaco com os atributos `HttpOnly`, `Secure` e `SameSite`, e revogue-a no servidor no logout. Não envie chaves de proxy ao navegador.

**Pronto quando** o operador cria e desativa contas, o colaborador entra com código e senha, e testes negativos provam que uma conta não acessa dados de outra.

### 2. OAuth compartilhado e atribuição

Separe o dono de uma credencial OAuth dos colaboradores que podem usá-la. Faça a conexão e renovação OAuth pelo navegador. No MVP, o responsável pela conta conecta pelo fluxo web e o operador atribui a credencial a um ou mais colaboradores por comando local. Depois do MVP, o operador assume todo o ciclo OAuth.

Mantenha tokens criptografados. Faça a atribuição muitos-para-muitos em uma migração aditiva. Preserve os registros e as chaves de proxy atuais. A aplicação autentica o colaborador pela sessão interna e escolhe uma credencial que esteja atribuída a ele.

**Pronto quando** uma credencial pode servir colaboradores autorizados diferentes, cada um permanece identificado nos registros, e RPM e uso diário continuam compartilhados pela credencial.

### 3. Chat, conversas e histórico do colaborador

Adicione uma API REST de chat que usa a sessão interna para identificar o colaborador. Crie a entidade de conversa desde o início, embora a primeira interface mostre uma conversa por colaborador. Associe cada execução a colaborador, conversa e credencial OAuth.

Continue usando o encaminhamento e a captura SSE atuais. Grave o prompt e a resposta completos. Mantenha o histórico isolado por colaborador e permita que a governança consulte o conjunto autorizado. Anexos ficaram fora do chat inicial; na evolução do chat, a migração `0010_chat_attachment_downloads` passou a guardar conteúdo criptografado para download pelo dono da conversa, além de nome, tipo, tamanho e referência técnica.

Se a renovação OAuth for necessária antes de enviar a mensagem ao upstream, preserve o texto e tente enviá-lo uma vez após reconectar. Não repita a mensagem se o upstream já a recebeu.

**Pronto quando** conversas e execuções persistem, colaboradores consultam apenas o próprio histórico, e o proxy existente continua funcionando com as chaves atuais.

### 4. Análise local, alertas e acesso de governança

Analise prompts com regras locais para vazamento de dados sensíveis e tentativas de contornar políticas ou instruções. Grave todos os achados com categoria, regra e confiança. Não bloqueie o envio.

Envie e-mail somente para regras marcadas como alta confiança. O e-mail inclui categoria e referência protegida, nunca o prompt. Persista alertas antes do envio e repita tentativas sem atrasar a resposta do chat. Configure o endereço de governança no ambiente protegido do serviço. Crie APIs de governança para leitura de conteúdo bruto e registre cada leitura e exportação.

**Pronto quando** achados e e-mails podem ser consultados e testados sem expor conteúdo em notificações, e cada acesso bruto fica associado ao usuário, horário e interação.

### 5. Retenção e métricas agregadas

Crie um comando diário idempotente, chamado pelo agendador do ambiente, para excluir conteúdo bruto expirado. Ele remove prompt, resposta, eventos e evidências que possam conter trechos do prompt depois de 90 dias. Consolide antes métricas sem identificação e mantenha os agregados por 12 meses. A governança consulta e exporta relatórios por departamento e período, categoria de achado, latência e erros.

**Pronto quando** uma execução de retenção em banco descartável exclui conteúdo vencido, preserva agregados no prazo definido e registra falhas sem apagar dados parcialmente.

## Compatibilidade e migrações

Faça migrações aditivas. Não apague nem reassocie credenciais, chaves ou execuções existentes sem uma regra explícita. Os runs antigos não identificam com segurança qual colaborador usou uma credencial OAuth compartilhada. Mantenha-os sem colaborador associado, fora do histórico individual, disponíveis somente à governança e sujeitos à retenção definida.

## Quality gate com testes e AEC

Rode os testes existentes e os novos testes da etapa em um PostgreSQL descartável migrado. O gate atual chama `gateway.tests.test_proxy`, `backend.tests.test_store` e `gateway.tests.test_internal_auth`. Amplie o comando do AEC quando novos módulos de teste entrarem. Sem `HARNESS_TEST_DATABASE_URL`, os testes que dependem de PostgreSQL são ignorados.

Para cada etapa, execute `python tools/aec_cycle.py scan` com `HARNESS_TEST_DATABASE_URL` apontando para esse banco descartável. O scan usa o Codex CLI 0.163 ou superior e executa QA somente leitura primeiro. Se o QA confirmar defeito de lógica ou eficiência em código Python, o AEC pode chamar o implementador em worktree isolada. O implementador preserva a função dos módulos e o gate executa os testes. Revise qualquer resultado em `WAITING_APPROVAL`; não aprove nem faça merge automaticamente.

Cada run mantém um SQLite próprio em `.audit/aec/<run_id>/aec.sqlite`. Consulte-o com `python tools/aec_cycle.py report <run_id>` e `aec --database .audit/aec/<run_id>/aec.sqlite approvals pending`.

## Migração de runs antigos

O proxy atual associa runs a credenciais OAuth, mas não registra qual colaborador iniciou cada execução. Não atribua esses prompts a uma identidade interna por inferência. Mantenha os registros sem colaborador, visíveis apenas para a conta de governança e sujeitos à retenção de 90 dias. Apague também evidências que possam conter trechos do prompt; somente agregados sem identificação permanecem por 12 meses.

## Fora deste roadmap

- Interface web do chat e console de governança.
- Redis e regras de cache.
- Armazenamento genérico de arquivos fora das conversas; os anexos de chat com download foram acrescentados na migração `0010_chat_attachment_downloads`.
- Disponibilidade, implantação, backups e recuperação de desastre.
- Funcionalidades avançadas e agentes.
