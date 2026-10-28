# Como o Hermes implementa browser use

Pesquisa feita em 26/10/2026 nas documentações e no código públicos do repositório oficial [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent). O fluxo descrito é o da branch `main` consultada nessa data.

## Fluxo principal

1. O agente recebe a ferramenta `browser_exec`, com `code` Python e opções de sessão/timeout. A ferramenta executa um bloco de passos, em vez de expor cada clique como uma chamada separada.
2. O Python roda com helpers como `new_tab`, `goto_url`, `page_info`, `js`, `fill_input` e `capture_screenshot`. Eles comandam o navegador via CDP, através do `browser-harness` (o driver da Browser Use CLI).
3. Cada execução começa um interpretador Python novo, mas o navegador e suas abas/cookies persistem na sessão. O nome `session` separa navegadores para trabalhos simultâneos.
4. O runtime fornece um endpoint CDP: normalmente inicia Chromium isolado por sessão; também pode usar provedores cloud ou conectar um Chrome/Brave/Edge existente com `/browser connect`.

## Há uma extensão?

No fluxo principal documentado, não. O Hermes inicia um navegador próprio ou se conecta a um navegador Chromium por CDP. `/browser connect` é a alternativa mais próxima para controlar um navegador já aberto, mas é um comando da CLI que configura CDP; a documentação não descreve uma extensão instalada no navegador.

Isso sugere duas peças distintas para o HarnessCastelo: a ferramenta do agente define as ações e devolve resultados; a extensão, se a meta for controlar a sessão normal do usuário, pode atuar como ponte para a aba/navegador existente. A extensão não é necessária para reproduzir o caminho padrão do Hermes com Chromium próprio.

## Segurança e limites relevantes

`browser_exec` executa Python escrito pelo modelo no host, então o Hermes só a disponibiliza junto do toolset `terminal`. O navegador local padrão usa perfil temporário e é encerrado por inatividade; usar o perfil real é opt-in. Isso importa ao escolher se a extensão vai expor apenas ações de página ou também acesso amplo ao navegador/host.

## Fontes primárias

- [Guia Browser Automation](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/browser.md) — helpers, sessões, CDP, tipos de navegador e condições de disponibilidade.
- [Referência de ferramentas](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/reference/tools-reference.md) — descrição e parâmetros de `browser_exec`.
- [Código de `browser_use_cli.py`](https://github.com/NousResearch/hermes-agent/blob/main/tools/browser_use_cli.py) — schema e execução da ferramenta.
- [Código de `browser_tool.py`](https://github.com/NousResearch/hermes-agent/blob/main/tools/browser_tool.py) — gerenciamento de sessões do browser.
- [Instruções de arquitetura em `tools/AGENTS.md`](https://github.com/NousResearch/hermes-agent/blob/main/tools/AGENTS.md) — mapa do runtime: `browser_use_cli.py`, `browser_session.py` e `browser_launcher.py`.
