import os
from pathlib import Path

# Diretório onde ficam os arquivos auth-*.json
AUTH_DIR = Path(os.environ.get("PROXY_AUTH_DIR", Path(__file__).resolve().parent / "auth"))

# Arquivo de registro client_key -> credencial
REGISTRY_FILE = Path(
    os.environ.get(
        "PROXY_REGISTRY",
        Path(__file__).resolve().parent / "registry" / "registry.json",
    )
)

# Backend do Codex
CODEX_BACKEND = os.environ.get("CODEX_BACKEND", "https://chatgpt.com/backend-api/codex")

# Timeout do upstream (segundos)
UPSTREAM_TIMEOUT = float(os.environ.get("UPSTREAM_TIMEOUT", "300"))
UPSTREAM_CONNECT_TIMEOUT = float(os.environ.get("UPSTREAM_CONNECT_TIMEOUT", "30"))

# client_id usado no refresh, por tipo de credencial
CLIENT_ID_BY_TYPE = {
    "personal_oauth": "app_EMoamEEZ73f0CkXaXp7hrann",
    "service_account": "app_EMoamEEZ73f0CkXaXp7hrann",
    "workspace": "app_EMoamEEZ73f0CkXaXp7hrann",
}
