# Especificação: verificação comum de acesso à governança

## Objetivo

Definir o escopo mínimo de uma função compartilhada que responda somente se a função e a concessão de um colaborador lhe dão acesso de governança. O objetivo é evitar que a mesma regra de elegibilidade seja repetida e evolua de forma diferente entre os módulos.

Esta especificação não altera a política atual nem autoriza, por si só, o acesso a qualquer registro ou organização.

## Regra atual a preservar

A elegibilidade atual é verdadeira quando:

- `role == "governance"`; ou
- `can_govern` é verdadeiro.

Caso contrário, é falsa. A regra deve funcionar tanto com entidades `Employee` do backend quanto com `EmployeeInfo` usado pela captura, sem exigir que a função consulte o banco ou conheça uma camada HTTP.

## Escopo da função

A função compartilhada deve:

- receber os valores de papel e concessão já disponíveis no objeto do colaborador;
- retornar um booleano conforme a regra acima;
- ser pura: não consultar banco, sessão, configuração, rede ou relógio;
- não lançar exceções para representar falta de permissão;
- não mudar mensagens HTTP, exceções de domínio ou formatos de resposta dos chamadores.

A assinatura concreta e o módulo de destino serão escolhidos na implementação para evitar uma abstração de tipos que os consumidores atuais não precisam. A função não deve aceitar objetos genéricos com reflexão nem criar uma hierarquia de permissões.

## Chamadores previstos

Na primeira alteração, substituir apenas as verificações duplicadas da mesma regra em:

- `backend/chat.py`: leituras de runs pela governança;
- `backend/governance.py`: consultas de achados e alertas;
- `backend/knowledge.py`: operações de gestão de documentos e departamentos;
- `backend/capture_app/security.py`: dependências de operador, leitura de conteúdo e analytics.

Cada chamador mantém as demais verificações e comportamentos que já possui. Não ampliar o conjunto de rotas nem alterar a política de quem tem acesso.

## Responsabilidades que permanecem nos chamadores

A função não substitui nem incorpora:

- validação de sessão/autenticação;
- conta inexistente, desativada ou com troca de senha obrigatória;
- escopo de organização, departamento, colaborador ou recurso;
- auditoria de leitura permitida ou negada;
- conversão da decisão em `403`, `404`, `PermissionError` ou exceção própria;
- autorização de máquina, OAuth ou credenciais;
- decisões futuras sobre concessão, revogação ou segregação de funções.

Essas regras variam entre os fluxos. Por exemplo, o backend valida estado do colaborador junto da leitura; a captura faz autenticação e validação de senha obrigatória na dependência de sessão, e algumas rotas registram auditoria de acesso negado. A centralização não deve remover essas diferenças.

## Compatibilidade e segurança

A implementação deve manter os resultados atuais para todas as combinações de `role` e `can_govern`. Deve preservar as verificações de organização e recurso após a decisão de elegibilidade; a função nunca deve transformar uma permissão global de governança em acesso entre organizações.

Não alterar dados, esquema, migrações, tokens, cookies, contratos HTTP ou regras de auditoria nesta mudança.

## Testes de aceitação

Testar a função para estes casos:

1. `role="governance"`, `can_govern=False` → permitido;
2. `role="collaborator"`, `can_govern=True` → permitido;
3. `role="collaborator"`, `can_govern=False` → negado.

Nos testes existentes dos chamadores, manter cobertura de que:

- colaborador inelegível continua sem acesso;
- colaborador desativado ou com troca de senha pendente continua sem acesso nos caminhos que já os rejeitam;
- organização e recurso fora do escopo continuam inacessíveis;
- auditoria e respostas HTTP/exceções permanecem inalteradas.

## Fora de escopo

- Dividir `backend/chat.py` por responsabilidades;
- criar uma matriz corporativa de permissões;
- mudar quais papéis podem receber `can_govern`;
- unificar todas as verificações de autenticação e autorização do sistema;
- adicionar interfaces, injeção de dependências ou configuração de políticas.

## Critério de conclusão

A regra de elegibilidade prevista usa uma implementação compartilhada em todos os chamadores listados, os testes direcionados passam e as verificações locais de estado, escopo, auditoria e resposta continuam nos respectivos chamadores.
