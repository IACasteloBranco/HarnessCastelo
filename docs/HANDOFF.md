# Continuidade do Maximus AI

## Onde paramos

O frontend em `frontend/public/` cobre login interno, conexão OAuth, chat com várias conversas, busca, projetos privados, anexos, prévia e download de arquivos, transcrição local, criação de PDF/CSV/XLSX, governança e gerenciamento de contexto. As referências visuais e logos necessárias estão no repositório. A interface pode ser vista sem conta real com a prévia descrita em `frontend/README.md`.

O contexto possui um **perfil em texto único por colaborador**, atualizado por uma chamada adicional à IA após respostas concluídas no chat web. O colaborador pode corrigir ou apagar o perfil em **Meu contexto**. Notas de instrução ou memória do perfil, projeto e conversa são gerenciadas separadamente. O perfil e as notas aplicáveis entram nos próximos prompts. Memórias automáticas pessoais do formato anterior foram copiadas para o perfil pela migração `0015_seed_user_profile`; as notas originais foram preservadas.

A implementação e os testes de integração usam PostgreSQL. A última migração é `0015_seed_user_profile`. No ambiente de desenvolvimento atual, o servidor HTTPS usa `https://localhost:18445/`; esse endereço funciona apenas na máquina que executa o serviço.

## Retomar em outra máquina

1. Após publicar a branch `feature/maximus-mvp-context`, clone-a e instale as dependências de `requiriments.txt` em um ambiente Python.
2. Copie `.env.example` para `.env`, configure PostgreSQL e gere uma chave Fernet para `TOKEN_ENCRYPTION_KEY`. O arquivo `.env` não é enviado ao GitHub. Para abrir dados criptografados de uma instalação existente, use a **mesma** chave e restaure o banco correspondente; uma chave nova não descriptografa tokens e anexos antigos.
3. Suba o PostgreSQL, execute `python -m alembic upgrade head` e siga o provisionamento de colaboradores e credenciais OAuth do `README.md`. O GitHub contém código e assets, não os dados do banco, senhas temporárias, tokens OAuth, certificado local ou o modelo de transcrição baixado.
4. Para ver a interface sem banco ou OAuth, execute `python -m frontend.dev_preview` e abra `http://localhost:18444/`. Para o uso real, siga o comando HTTPS do `frontend/README.md` e conecte uma credencial OAuth atribuída ao colaborador.

O procedimento de instalação em Windows está no `README.md`, mas o fluxo completo ainda precisa ser validado nesse sistema. O modelo local de transcrição requer o download descrito em `frontend/README.md`.

## Validação feita

- Migrações `0013` a `0015` aplicadas no PostgreSQL local e em um banco isolado de testes.
- Suíte `gateway.tests.test_chat`: 22 testes passaram, incluindo isolamento de contexto, atualização cumulativa do perfil e proteção de edição manual.
- `frontend/tests/preview.py`: passou no Chrome com chat, projetos, arquivos e edição do perfil em desktop e celular.
- `node --check frontend/public/app.js` e `git diff --check`: passaram.

## Próximas decisões e verificações

- Testar a revisão automática do perfil com a conexão OAuth real. Ela consome uma chamada adicional e ocorre no chat web após a resposta; se a aba for fechada antes dessa chamada, a revisão pode não acontecer.
- Revisar o perfil gerado: o filtro local descarta padrões sensíveis comuns, mas não garante que a IA classifique todos os dados corretamente.
- Definir se projetos precisarão de arquivos de referência persistentes. Hoje eles têm notas de contexto e conversas, mas anexos continuam vinculados à mensagem em que foram enviados.
- Validar instalação completa, OAuth e transcrição no Windows antes de usá-lo como ambiente de trabalho principal.
