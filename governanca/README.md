# Governança de IA

Este produto reúne a extensão de navegador e os módulos de proteção e governança que serão desenvolvidos em seguida.

- `extension/`: extensão Chrome atual para ChatGPT e Claude.
- `server/`: contém o detector local em `data_protection.py`; DLP remoto, analytics e API ainda serão construídos. A API atual da extensão continua integrada ao gateway legado.

Manter a inspeção obrigatória e as decisões de política no servidor é necessário para que as regras não dependam apenas do navegador.
