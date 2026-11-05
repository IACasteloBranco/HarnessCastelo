# Spec — Plano de fechamento de gaps de governança de IA (Fase 1)

## Objetivo

Fechar, com evidência reproduzível, a maior quantidade possível de pendências da aba “Gap Analysis Harness” que já têm algum mecanismo identificado como “Parcial”. A fase começa por atualizar o escopo real e executar/verificar o que já existe; só depois propõe mudanças pontuais para lacunas confirmadas. Não tratar existência de código ou teste unitário como controle eficaz sem validação.

## Fonte e limites

- Fonte inicial: `docs/Gap_Analysis_HarnessCastelo_Castelo_Branco_Atualizado.xlsx`, abas “Gap Analysis Harness”, “Plano de Ação” e “Resumo da Auditoria”.
- Riscos-alvo: R01–R07, R16, R18–R21, R24 e R28, classificados como parciais na planilha.
- A planilha foi produzida para outra branch e declara que mudanças locais não foram avaliadas. O repositório atual contém alterações não commitadas. O primeiro passo é estabelecer o que será incluído na revisão; não assumir que a avaliação anterior descreve essas alterações.
- R08–R15, R17, R22–R23 e R25–R27 não entram no escopo de fechamento desta fase: a planilha não apresenta evidência parcial suficiente ou são frentes de implementação/decisão maiores. Podem ser planejadas em fases posteriores.
- Esta spec não declara conformidade com LGPD, NIST AI RMF, ISO/IEC 42001 ou OWASP. Ela define trabalho de verificação e evidências.

## Princípios

1. Separar estado de implementação de estado de validação; nunca converter “não testado” em “validado”.
2. Usar primeiro testes e mecanismos existentes, sem introduzir nova arquitetura, dependência ou serviço nesta fase.
3. Testar com dados sintéticos; não armazenar prompts, documentos, segredos ou identificadores reais nos relatórios.
4. Falha de inspeção deve continuar bloqueando o envio nos caminhos em que a inspeção é obrigatória. Não abrir exceções silenciosas.
5. Não impor novas políticas de modelos, consentimento, retenção, auditoria ou permissões sem aprovação conforme `docs/backend-security-decisions.md`.
6. Não reescrever as alterações locais existentes nem misturar sua autoria. Registrar o estado do Git e analisar apenas escopo autorizado.

## Sequência de execução — menor dificuldade primeiro

### T0 — Baseline e correção do escopo documental (muito baixa)

**Trabalho**
- Registrar branch, commit-base, data da revisão e `git status` sem incluir segredos ou conteúdo de `.env`.
- Identificar quais alterações locais pertencem ao trabalho em avaliação; se não forem parte da revisão, excluí-las explicitamente do relatório.
- Atualizar a coluna “Validação local / QA” para dizer precisamente se o código foi inspecionado, se o teste foi executado e em qual ambiente. Não usar “código local não fornecido” quando a revisão ocorre neste checkout.
- Preservar a distinção entre “não identificado na amostra” e “inexistente”.

**Aceite**
- Escopo, branch/commit e exclusões estão registrados.
- Totais e estados da planilha conferem com os 28 riscos; nenhuma mudança local é considerada avaliada sem inspeção explícita.

### T1 — Inventário executável dos controles parciais (baixa)

**Trabalho**
- Mapear, para cada risco-alvo, o controle e o caminho de código/teste atuais, confirmando as referências da planilha contra o checkout.
- Registrar comandos exatos de teste existentes para servidor e extensão e a saída real (passou/falhou/não executável).
- Identificar cobertura já existente para detecção/mascaramento, anexos, fail-closed, retenção, analytics, identidade e cotas; não criar testes duplicados.

**Aceite**
- Cada risco-alvo tem evidência de código/teste ou uma lacuna confirmada, com caminho e símbolo/arquivo.
- Os testes existentes foram executados ou têm bloqueador documentado; resultados não são inferidos.

### T2 — Testes focados de proteção de dados e anexos (baixa a média)

**Riscos**: R01, R02, R04, R05, R07 e R28.

**Trabalho**
- Estender testes existentes apenas para casos descobertos como faltantes: identificadores/documentos, segredo, conteúdo financeiro e arquivo/anexo não inspecionado.
- Confirmar comportamento para texto e para fluxo que contém somente anexo; quando o conteúdo não puder ser inspecionado, verificar bloqueio ou exceção formal já aprovada.
- Verificar que logs e mensagens de erro não reproduzem o valor sensível sintético.

**Aceite**
- Casos positivos e negativos sintéticos cobrem os limites declarados da detecção.
- Envio não inspecionado não passa pelo caminho protegido; falha de inspeção não libera envio.
- Testes passam e registram comando/ambiente. Qualquer limitação conhecida fica explícita, sem classificar como fechado.

### T3 — Verificações de acesso, identidade e analytics (média)

**Riscos**: R16, R20 e R24.

**Trabalho**
- Executar testes de autorização existentes para leitura de interações/capturas e confirmar trilha de ator/alvo nas operações cobertas.
- Verificar se credencial compartilhada e identidade individual são distinguíveis na aplicação e nos logs; não presumir que OAuth compartilhado equivale a identidade individual.
- Confirmar que analytics expõe apenas campos previstos e que não cria ranking/avaliação individual além da finalidade documentada. Se a finalidade não estiver aprovada, registrar bloqueio decisório, sem inventar regra técnica.

**Aceite**
- Acesso não autorizado é negado nos testes aplicáveis, e a auditoria não contém conteúdo bruto nem segredo.
- Limites de identidade compartilhada e finalidade de analytics estão documentados; decisões corporativas pendentes permanecem abertas.

### T4 — Limites de consumo e retenção (média a alta)

**Riscos**: R18 e R21.

**Trabalho**
- Verificar cotas existentes por credencial/departamento e testar limite, erro e recuperação sem chamadas externas reais ou custo não controlado.
- Testar rotina de expurgo com dados sintéticos e confirmar escopo de prompts, respostas e metadados conforme comportamento implementado.
- Distinguir expurgo da base ativa de retenção em logs/backups. Não declarar eliminação completa sem evidência de cada camada.
- Revisar política de retenção e finalidade com responsáveis; não alterar prazo nem comportamento antes de aprovação.

**Aceite**
- Limites de quota têm teste reproduzível e falha previsível; não alegar kill switch de agente se o produto não tiver agente.
- Expurgo da camada testada tem evidência; backups/logs e prazo corporativo ficam explicitamente pendentes se não verificáveis.

### T5 — Teste ponta a ponta na extensão e fechamento do relatório (alta)

**Riscos**: R01–R07 e R28, consolidando T2–T4.

**Trabalho**
- Exercitar o caminho real protegido da extensão (eventos de envio e barreira de rede) com ambiente de teste e dados sintéticos, incluindo texto, anexo e falha do serviço de inspeção.
- Confirmar que o texto efetivamente enviado é o texto aprovado/mascarado, sem corrida com edição do rascunho ou alteração da política, quando aplicável ao fluxo existente.
- Registrar navegador/versão, extensão/commit, ambiente, comandos, resultado, evidência sem conteúdo sensível e defeitos encontrados.
- Atualizar status por risco em eixos independentes: implementação e validação. Só marcar “validado” quando os critérios desta spec forem atendidos.

**Aceite**
- Casos P0 selecionados têm resultado reproduzível e evidência revisável.
- Cada falha gera item de correção com responsável sugerido e critério de aceite; não esconder falhas agregando média ou score.
- Resumo executivo recalculado a partir dos estados individuais e revisado por uma segunda pessoa.

## Critério de fechamento por risco

Um risco só pode ser marcado como “Fechado na Fase 1” quando:

- o controle implementado está identificado no caminho efetivamente usado;
- os testes relevantes passaram no ambiente declarado, incluindo falha/negação quando aplicável;
- evidência não contém dados reais ou segredos;
- limitações residuais e dependências decisórias estão anotadas;
- responsável técnico e responsável de negócio aceitaram o resultado.

Se algum item falhar, usar “Em implementação”, “Testado com falhas/ressalvas”, “Pendente de decisão” ou “Não testado”, conforme o caso. “Parcial” não significa “pronto, só falta testar”.

## Entregáveis

1. Inventário de escopo atualizado na planilha, sem sobrescrever silenciosamente a avaliação anterior.
2. Resultados de testes reproduzíveis para os riscos executados, com comandos, versões e status.
3. Lista curta de gaps remanescentes, cada qual com risco, evidência faltante, dono sugerido e critério de aceite.
4. Resumo executivo recalculado e revisado; sem alegação de certificação ou conformidade formal.

## Fora de escopo

- Implementar cobertura completa de todos os 28 riscos.
- Construir detector semântico novo, pipeline de leitura de PDF/XLSX ou integração externa de DLP.
- Introduzir bloqueios corporativos novos sem decisão aprovada.
- Provar implantação em produção, contratos de fornecedores, base legal, recuperação de backups ou cobertura de ferramentas fora da extensão.
- Corrigir ou reformatar alterações locais não relacionadas.

## Dependências e riscos

- A avaliação válida depende de definir quais alterações locais podem ser incluídas; a árvore de trabalho já está modificada.
- Alguns riscos exigem decisão de negócio/jurídica e não podem ser encerrados apenas por testes de código.
- Extensão de navegador não cobre automaticamente aplicações, canais, anexos e integrações fora de seu alcance.
- Testes de retenção não provam expurgo de backups ou cópias externas sem acesso e evidência dessas camadas.
