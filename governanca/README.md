# Governança de IA

Este produto reúne a extensão de navegador e os módulos de proteção e governança que serão desenvolvidos em seguida.

- `extension/`: extensão Chrome atual para ChatGPT e Claude.
- `server/`: serviço independente da extensão, com autenticação, inspeção local e integração com Google Sensitive Data Protection. Não executa o proxy do Codex.

Manter a inspeção obrigatória e as decisões de política no servidor é necessário para que as regras não dependam apenas do navegador.
