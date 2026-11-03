# Pacote compartilhado

`identity/` contém os modelos de identidade PostgreSQL, autenticação, autorização e os fluxos de investigação usados pelos serviços. Maximus e Governança devem importar esses contratos, sem manter implementações próprias.

`migrations/` contém o histórico Alembic compartilhado. Execute `python -m alembic upgrade head` a partir da raiz do monorepo; o arquivo `alembic.ini` aponta para esse diretório.

A captura e seu analytics pertencem a `governanca/server/capture_app/`. A análise departamental pertence ao Maximus. Não mova analytics de um produto para o pacote compartilhado.
