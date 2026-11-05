# Evidências — Fase 1 de governança de IA

## Escopo executado

- Revisão limitada ao commit `d38ce90df9a082d07f8719f031c0c764b3ae745b` (`codex/separate-maximus-governanca-to-main`).
- Data da execução: 4 de novembro de 2026.
- As alterações locais e os arquivos não commitados não foram considerados nem alterados.
- Os testes foram executados sobre uma extração temporária do commit, separada da árvore de trabalho, para não misturar mudanças locais.
- A planilha gap analysis e esta spec não fazem parte do commit-base; a planilha foi usada apenas como referência fornecida, não atualizada.

## Resultado de QA

| Suíte | Resultado | Observação |
|---|---:|---|
| `python -m unittest discover -s governanca/server/tests -v` | 30 passaram; 1 ignorado | O teste `test_governance_capture_access_is_scoped_and_audited` requer PostgreSQL descartável. |
| `node --test governanca/extension/tests/*.test.mjs` | 68 passaram; 0 falharam | Executado em Node no snapshot do commit. |

O snapshot também contém testes específicos para inspeção de dados, mascaramento, falha fechada, bloqueio de rede, prévia mascarada, arquivos como metadados e analytics/autorização. A aprovação dos testes comprova esses comportamentos cobertos no snapshot, não eficácia em produção nem cobertura completa de cada cenário da matriz.

## Inventário revisado — riscos parciais

| Risco | Evidência no snapshot | Estado após esta fase |
|---|---|---|
| R01 — CPF/segredos e dados pessoais | `governanca/server/data_protection.py`, `sensitive_data_protection.py`, `inspection.py`; testes Python de proteção e teste da extensão para chave privada/CPF. | Parcial; detectores e falha fechada cobertos em parte. RG/endereço e cobertura integral não demonstrados. |
| R02 — folha salarial | Fluxo da extensão inspeciona texto do compositor; `files.js` coleta metadados e não lê bytes. `blocker.test.mjs` confirma aceitação de envio somente com anexo. | Aberto: conteúdo salarial em anexo não é inspecionado. |
| R04 — certificados, senhas e tokens | `policy-engine.js` e testes de chave privada, credenciais e códigos de recuperação; DLP contextual no servidor. | Parcial; não há comprovação de cobertura de certificado A1/PFX e todos os tokens/secrets. |
| R05 — dados bancários | Há regras para CPF e estruturas financeiras limitadas no `policy-engine.js`; não foi encontrado detector específico de extrato/saldo/conta na busca executada. | Aberto/parcial; cobertura bancária não demonstrada. |
| R06 — segregação entre clientes | `capture_app/security.py` e consultas organizacionais; existe teste de isolamento e auditoria em `test_capture_governance.py`. | Parcial; teste principal requer PostgreSQL descartável e foi ignorado nesta execução. Não extrapolar para RAG/LLM. |
| R07 — documentos integrais | Extensão captura apenas metadados de anexos; não lê o conteúdo (`files.test.mjs`). | Aberto: minimização do prompt não inspeciona documento anexado. |
| R16 — contexto oculto/segredos de configuração | Há políticas de inspeção e bloqueio de segredos; nenhum teste específico de extração de instruções internas foi identificado na amostra pesquisada. | Não validado para esse cenário específico. |
| R18 — consumo/custos | Não foi localizado controle de custo/loop de agente na amostra da Governança. O escopo examinado não comprova quota do proxy Maximus. | Não validado nesta revisão limitada; exige avaliação do componente de quota correto. |
| R19 — Shadow AI | Manifesto da extensão limita origens cobertas; testes verificam destinos suportados. | Parcial; extensão não prova bloqueio global de ferramentas fora de suas origens. |
| R20 — identidade compartilhada | A extensão tem identidade de máquina/atribuição; a autorização da API usa sessão de colaborador. | Parcial; não prova que credenciais do provedor de IA sejam individuais nem resolve decisão corporativa de conta compartilhada. |
| R21 — retenção | `capture_app/db.py` implementa `clean_expired`; configuração limita `retention_days` a 1–90 dias em `settings.py`. Não foi executado teste de expurgo nesta fase. | Parcial/não testado; logs e backups não foram verificados e prazo requer decisão de negócio. |
| R24 — analytics individual | `capture_app/analytics.py` expõe dados agregados e, para governança, `by_employee`; há testes de acesso/analytics, mas o teste PostgreSQL foi ignorado. | Pendente de validação e decisão de finalidade/transparência para analytics individual. |
| R28 — inspeção e exceções | Inspeção textual fail-closed está coberta; arquivos permanecem metadados e podem seguir como envio somente com anexo. | Parcial; bypass por conteúdo de anexo permanece. |

## Gaps que continuam abertos

1. Anexos: definir e implementar bloqueio seguro, inspeção do conteúdo ou exceção formal para arquivo não analisável; executar QA em PDF/XLSX sintéticos. Não marcar R02/R07/R28 como fechados.
2. Escopo de DLP: ampliar e testar RG, endereço, folha, dados bancários e classes de segredo faltantes; usar valores sintéticos e conferir que logs não reproduzem conteúdo.
3. PostgreSQL: executar o teste de isolamento/auditoria somente com banco descartável configurado explicitamente; resultado não foi obtido nesta execução.
4. R16, R18, R20, R21 e R24: cenários específicos não foram validados por esta rodada. Retenção, identidade de provedor, finalidade de analytics e política de auditoria dependem também de decisões, não apenas de código.
5. Produção e canais externos: não houve teste em navegador real, prova de implantação, teste de backup/logs, nem validação fora das origens cobertas pela extensão.

## Decisões e limites

- Não foram alterados código, políticas, testes ou a planilha. A execução confirmou cobertura existente e identificou evidências que não bastam para fechar os gaps; ampliar a proteção de anexos ou impor novas restrições altera comportamento de usuário e requer decisão explícita.
- “Não validado” e “não evidenciado” não significam que o controle inexista; são limites da amostra e da execução descritas acima.
- Não é declaração de conformidade ou certificação.
