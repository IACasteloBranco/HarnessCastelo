# Extensão HarnessCastelo

A extensão aplica a política de envio e captura prompts e respostas observados no ChatGPT e no Claude. O conteúdo, o colaborador, o departamento e os metadados de contexto são enviados ao gateway local; arquivos são registrados somente por metadados observáveis.

## Desenvolvimento local

1. Inicie o PostgreSQL, aplique as migrações e rode `python -m gateway.serve` na raiz do repositório.
2. Em `chrome://extensions`, carregue a pasta `browser-extension/` como extensão descompactada.
3. Entre pelo popup com a conta interna do Harness, solicite o vínculo da instalação e aguarde aprovação da Governança.
4. Leia e confirme o aviso de privacidade, habilite a captura e recarregue as abas do ChatGPT e do Claude.

O endpoint publicado é `https://app.castelotecnologia.com.br`. Para desenvolvimento local, altere `src/background/config.js` e a permissão correspondente em `manifest.json`. Preserve a chave pública do manifesto, que mantém o ID de extensão autorizado pelo gateway. A sessão da extensão renova automaticamente enquanto houver uso; após 90 dias sem uso, será necessário entrar novamente.

No ChatGPT, a extensão também registra metadados técnicos do stream. No Claude, a conclusão da resposta é estimada quando o texto renderizado fica estável e o controle de interrupção some. A captura reflete o conteúdo observável no navegador e não comprova que o provedor recebeu ou processou todos os dados.
