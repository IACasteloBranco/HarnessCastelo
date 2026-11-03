# Maximus

Maximus é o projeto de chat e proxy Codex deste monorepo. O gateway e o frontend continuam na raiz (`gateway/`, `frontend/`); os módulos de domínio Maximus ficam em `backend/`, exceto o analytics departamental do chat, em `department_analysis.py`.

Identidade e modelos PostgreSQL em `backend/internal_auth.py` e `backend/database.py` são compartilhados com Governança. A captura/inspeção da extensão e seu analytics não pertencem a este projeto; ficam em `../governanca/`. Evite dependências de Maximus no servidor da Governança.
