# Proteção local de texto

`governanca/server/data_protection.py` entrega inspeção sem rede, banco, logs ou dependências novas. Não está conectado ao envio de mensagens nesta etapa. Portanto, instalar este código ainda não protege os envios existentes.

`detect(text)` retorna tuplas imutáveis de `Finding(category, start, end)`, sem copiar o valor identificado. As posições são índices de caracteres Python, com início inclusivo e fim exclusivo, sobre o texto original. Não são bytes nem posições UTF-16 do JavaScript. Um consumidor na extensão precisará converter essas posições antes de usá-las em seleções do editor. A detecção mantém sobreposições para que a política possa avaliar todas as categorias.

`inspect(text, policy, policy_version=...)` exige uma ação explícita para cada `Category`: `Action.ALLOW`, `Action.MASK` ou `Action.BLOCK`. Não existe política corporativa implícita. Um CNPJ encontrado pode ser permitido. Qualquer ocorrência bloqueada prevalece, inclusive dentro de um e-mail permitido, e retorna `text=None`. O chamador deve impedir o envio nesse caso.

Na substituição, a prioridade de sobreposições é EMAIL, CNPJ, CPF, PHONE. Apenas ocorrências configuradas para substituição participam dessa seleção. Cada ocorrência recebe um marcador sequencial por categoria, mesmo se o valor se repetir. Marcadores já presentes no texto são preservados e sua numeração é pulada. O restante do texto fica intacto. Os achados sempre apontam para o original, não para a saída.

```python
from backend.data_protection import Action, Category, inspect

policy = {category: Action.MASK for category in Category}
policy[Category.CNPJ] = Action.ALLOW
decision = inspect("CPF 123.456.789-09", policy, policy_version="exemplo-1")
assert decision.text == "CPF [CPF_1]"
```

## Cobertura e limites

CPF é numérico, com ou sem pontuação e com verificação dos dois dígitos. CNPJ aceita o formato numérico e o alfanumérico, com ou sem pontuação; letras minúsculas são aceitas e normalizadas apenas para a validação. Os dígitos usam módulo 11 e valor ASCII menos 48 conforme o [manual técnico da Receita Federal](https://www.gov.br/receitafederal/pt-br/centrais-de-conteudo/publicacoes/documentos-tecnicos/cnpj/manual-dv-cnpj.pdf), consultado em 3 de novembro de 2026. Validar os dígitos não comprova existência ou titularidade de um cadastro.

E-mail usa sintaxe ASCII comum com domínio contendo ponto; endereços internacionais e formas RFC com aspas ficam fora deste detector. Telefone aceita números brasileiros com DDD válido, fixos iniciados em 2 a 5, celulares iniciados em 9 e código internacional opcional `+55`. Números locais sem DDD, ramais e outros países ficam fora. Um número com formato válido pode ser um identificador sem relação com telefone; Regex não resolve essa ambiguidade. Os testes usam textos sintéticos e domínios `.invalid`.

A saída mascarada não é presumida anônima. Este módulo não guarda mapa reversível; uma integração que acrescente reversibilidade estará fazendo pseudonimização. Não registrar texto original, saída ou posições como trilha padrão. A auditoria futura deve conter apenas usuário, ferramenta, horário, categorias e contagens, ação e versão da política. Qualquer retenção de conteúdo precisa de finalidade e acesso definidos.

## Pontos de integração seguintes

- `governanca/extension/src/content/blocker-bridge.js` já intercepta clique, Enter e submit, lê o editor e avalia a política. A inspeção obrigatória deve concluir antes de conceder a liberação. Quando houver alteração, mostrar a prévia e usar exatamente o texto aprovado, revalidando se o rascunho mudar. Falhas devem manter o bloqueio.
- `governanca/extension/src/content/blocker-main.js` protege o caminho de rede. A nova inspeção deve preservar essa barreira, sem depender apenas dos eventos do editor. `policy-engine.js` contém a política atual; não substituir silenciosamente suas regras.
- `governanca/extension/src/background/service-worker.js` centraliza a comunicação autenticada e os metadados de decisão. Usar esse caminho para chamar o backend e manter credenciais fora do conteúdo da página e da extensão.
- No chat próprio, preservar `gateway/chat.py` → `backend/chat.py` → `backend/store.py` → `gateway/forwarder.py`. A futura inspeção precisa ocorrer antes do encaminhamento ao Codex, preservando admissão, idempotência e os contratos de runs. Não foi criada rota nesta entrega.

O Google Cloud Sensitive Data Protection fica para a etapa de serviço autenticado. A documentação atual descreve [`content.inspect` para inspeção síncrona e `content.deidentify` para transformação](https://docs.cloud.google.com/sensitive-data-protection/docs/sensitive-data-protection-overview). A [documentação de desidentificação](https://docs.cloud.google.com/sensitive-data-protection/docs/deidentify-sensitive-data) orienta selecionar os `infoTypes` relevantes, evitando trabalho desnecessário. Essas páginas foram verificadas em 3 de novembro de 2026; confirmar novamente ao implementar a integração. Processamento contextual deve ficar no serviço gerenciado, sem carregar modelo próprio na VM de 4 vCPUs e 8 GB.

PDFs, imagens, anexos, prévia no navegador, rotas autenticadas e persistência de auditoria não fazem parte desta entrega. Antes da próxima etapa, testar os caminhos de Enter, clique, submit e rede, falha de inspeção, edição durante a prévia e mudança de política durante a liberação.

## Verificação

Execute `python -m unittest governanca.server.tests.test_data_protection -v`. São testes puros sem banco; não há alteração de esquema nem necessidade de PostgreSQL nesta suíte.
