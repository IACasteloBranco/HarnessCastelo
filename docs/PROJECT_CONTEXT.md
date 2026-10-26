# Contexto do projeto

Este documento reúne fatos do repositório e objetivos já descritos pelo responsável pelo projeto. Ele serve de base para a conversa de alinhamento. As decisões marcadas como pendentes ainda não estão implementadas.

## Objetivo informado

O HarnessCastelo é um projeto interno para criar um harness próprio, apresentado aos colaboradores como **Maximus AI**. O valor central esperado é a governança das interações entre colaboradores e modelos de IA.

O gateway deverá analisar prompts para detectar padrões potencialmente nocivos. O banco próprio deverá armazenar interações e dados sobre o uso da ferramenta pelos colaboradores.

O plano inclui autenticação interna dos colaboradores e vinculação de uma ou mais contas ChatGPT, que podem ser compartilhadas entre colaboradores, organizados por departamentos. O frontend, o Redis e a infraestrutura digital ainda estão por desenvolver.

## Comportamento atual observado

O serviço FastAPI recebe chamadas em `/v1/{path}`. O cliente autentica com uma chave de proxy. O serviço valida a chave, aplica limites de uso, carrega a credencial OAuth associada e encaminha a chamada ao backend Codex do ChatGPT.

As requisições e os eventos da resposta são registrados no PostgreSQL. O modelo atual tem `accounts`, `credentials`, `client_keys`, `runs` e `run_events`. Tokens OAuth são criptografados antes de serem armazenados. Chaves de proxy são armazenadas como hashes.

O OAuth é iniciado pelo comando local `backend.scripts.create_auth`. O comando associa a credencial ao `user_id` informado. O repositório ainda não contém cadastro de organizações, departamentos, identidade interna de colaborador, login interno ou frontend.

## Organização do repositório

- `backend/` contém o modelo e o acesso ao banco, migrações, comandos operacionais e testes de persistência.
- `gateway/` contém a API atual de proxy, encaminhamento ao upstream, renovação OAuth e captura SSE.
- `frontend/` reserva um lugar para o cliente web. Ainda não há implementação.
- `docs/` contém o contexto do projeto e as decisões aprovadas.
- `tools/` contém o ciclo local de QA com AEC.

O gateway e o backend ainda compartilham o mesmo processo e a mesma base PostgreSQL. A separação atual organiza o código. Ela não define uma fronteira de implantação entre serviços.

## Decisões aprovadas para o primeiro release

- O gateway atende somente o ChatGPT Codex.
- O motor analisa e registra. Ele não bloqueia interações no primeiro release.
- PostgreSQL é a fonte persistente de verdade. Redis fica para depois do MVP como cache, sem substituir o armazenamento principal.
- Um operador local provisiona empresas, departamentos e colaboradores.
- O operador provisiona as contas internas de colaboradores e do responsável pela governança; entrega senhas temporárias para troca no primeiro login.
- O provisionamento é feito por comandos locais do operador; o primeiro frontend não inclui administração de contas.
- O sistema registra prompts e respostas por 90 dias. Gestores recebem métricas agregadas após esse prazo.
- Evidências de achados que possam repetir trechos do prompt são apagadas junto com o conteúdo bruto aos 90 dias; somente métricas agregadas sem identificação são mantidas por 12 meses.
- Para anexos enviados no chat, o sistema registra nome, tipo, tamanho e referência técnica. Desde a migração `0010_chat_attachment_downloads`, guarda também o conteúdo criptografado em tabela privada para download pelo colaborador dono da conversa. Anexos antigos continuam sem conteúdo recuperável. A retenção apaga os arquivos com os runs após 90 dias.
- Para arquivos criados a partir das respostas da IA, o sistema guarda PDF, XLSX ou CSV criptografado e vinculado ao run original. Somente o colaborador dono da conversa baixa o arquivo; a retenção de 90 dias o remove junto ao run. XLSX e CSV usam uma chamada adicional à IA e consomem cota.
- Projetos são privados por colaborador e agrupam conversas por `project_id`. Mover um chat altera o agrupamento e as notas de projeto aplicáveis às próximas mensagens; excluir o projeto devolve seus chats à lista geral e exclui suas notas de contexto. O perfil em texto único do colaborador e as notas do perfil, do projeto e da conversa são privados e modificam o prompt enviado à IA.
- O colaborador pode consultar o próprio histórico. Somente uma conta do responsável pela governança pode consultar interações de todos; gestores recebem métricas agregadas.
- Backend e gateway ficam em módulos separados no mesmo deploy.
- O código do colaborador identifica a conta; o login usa uma senha própria.
- O operador entrega uma senha temporária. O colaborador precisa trocá-la no primeiro login; o operador faz a recuperação.
- Cada departamento tem um código próprio, usado como identificador. O operador atribui os colaboradores aos departamentos.
- No primeiro release, o classificador observa vazamento de dados sensíveis e tentativas de contornar políticas ou instruções.
- O MVP atende uma empresa.
- O primeiro classificador usa regras locais.
- Todos os achados ficam registrados. O gateway envia e-mail imediato à governança somente para achados de alta confiança.
- Cada regra declara sua confiança; apenas regras marcadas como alta confiança geram e-mail.
- O endereço de e-mail da governança é configurado por variável protegida no ambiente do serviço.
- Métricas agregadas sem identificação ficam disponíveis por 12 meses após a remoção do conteúdo bruto.
- O responsável pela governança prepara análises agregadas para a liderança.
- A primeira entrega do frontend é o chat. Depois entram o console de governança e a lapidação do chat, incluindo múltiplas conversas e anexos; funcionalidades avançadas ficam para depois do MVP.
- O chat do MVP não usa agentes.
- Frontend e backend usam uma API REST JSON.
- Os alertas imediatos chegam por e-mail e não incluem o prompt.
- Cada leitura ou exportação de conteúdo bruto pela governança fica registrada.
- A governança prepara relatórios agregados no console e os exporta para a liderança.
- Os relatórios iniciais agregam volume de interações por departamento e período, categorias de achados, latência e erros, sem conteúdo de prompts nem identificação individual.
- O responsável pela conta ChatGPT a vincula ou renova uma vez pelo fluxo web; o operador atribui a credencial OAuth a um ou mais colaboradores autorizados. As contas internas e conversas permanecem separadas por colaborador, mesmo quando compartilham a credencial.
- Limites de RPM e de uso diário são compartilhados por credencial OAuth; o consumo também é registrado por colaborador.
- A sessão interna usa cookie opaco `HttpOnly`, `Secure` e `SameSite`, com expiração e revogação no servidor.
- APIs de governança, alertas, retenção e métricas agregadas fazem parte do backend do primeiro release, embora o console web venha depois do chat.
- Alertas de alta confiança são persistidos e repetidos em caso de falha de e-mail sem atrasar a resposta do chat.
- Um comando diário idempotente remove conteúdo bruto expirado e consolida métricas agregadas sem identificação, acionado pelo agendador do ambiente.
- Runs antigos que só identificam a credencial OAuth ficam sem colaborador atribuído, visíveis apenas à governança e sujeitos à retenção de 90 dias; não se infere autoria.
- Se uma mensagem exigir nova autenticação, o chat mantém o texto, reconecta e tenta reenviá-lo uma vez após a confirmação OAuth, somente se a mensagem ainda não chegou ao upstream.

## Decisões pendentes

- Quais são os ambientes, requisitos de disponibilidade, operação e recuperação?

## Limites desta nota

Esta nota registra decisões de escopo, não uma política operacional completa. Os requisitos de implantação, disponibilidade, operação e recuperação ficam para a etapa de infraestrutura.
