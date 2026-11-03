from functools import lru_cache
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    app_host: str = "127.0.0.1"
    app_port: Annotated[int, Field(ge=1, le=65535)] = 8000
    database_url: SecretStr | None = None
    database_path: Path = Path("./data/lab.sqlite3")
    capture_api_token: SecretStr | None = None
    operator_read_token: SecretStr | None = None
    lab_api_token: SecretStr | None = None
    retention_days: Annotated[int, Field(ge=1, le=90)] = 90
    max_prompt_chars: Annotated[int, Field(ge=1, le=1_000_000)] = 100_000
    max_response_chars: Annotated[int, Field(ge=1, le=1_000_000)] = 200_000
    max_url_chars: Annotated[int, Field(ge=1, le=8192)] = 4096
    max_attachments: Annotated[int, Field(ge=0, le=100)] = 20
    allowed_origins: str = ""
    machine_signature_required: bool = True
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: SecretStr | None = None
    google_extension_redirect_uri: str | None = None
    google_analytics_redirect_uri: str | None = None
    google_content_viewer_subs: str | None = None
    pilot_department_code: str | None = None
    google_workspace_domain: str = "castelobrancocontabilidade.com.br"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    def allows_pilot_department(self, department_code: str | None) -> bool:
        return bool(department_code) and (
            self.pilot_department_code == "*" or department_code == self.pilot_department_code
        )

    @property
    def content_viewer_subs(self) -> set[str]:
        return {item.strip() for item in (self.google_content_viewer_subs or "").split(",") if item.strip()}

    def allows_content_viewer(self, subject: str) -> bool:
        return subject in self.content_viewer_subs

    @property
    def uses_postgres(self) -> bool:
        return self.database_url is not None

    def validate_lab_configuration(self) -> None:
        if self.app_env.lower() not in {"local", "lab"}:
            raise ValueError("APP_ENV must be local or lab")
        if self.app_env.lower() == "lab" and not self.uses_postgres:
            raise ValueError("Lab requires DATABASE_URL for PostgreSQL")
        if self.database_url:
            database_url = urlsplit(self.database_url.get_secret_value())
            if database_url.scheme != "postgresql" or not database_url.hostname or not database_url.path.strip("/"):
                raise ValueError("DATABASE_URL must be a PostgreSQL URL with a host and database name")
        if self.app_env.lower() == "lab":
            required = (self.google_oauth_client_id, self.google_oauth_client_secret,
                        self.google_extension_redirect_uri, self.google_workspace_domain)
            if not all(required):
                raise ValueError("Lab requires Google OAuth configuration")
            if not self.google_extension_redirect_uri.startswith("https://"):
                raise ValueError("Google extension redirect URI must use HTTPS")
            if not self.machine_signature_required:
                raise ValueError("Lab requires machine signatures")
            if self.google_analytics_redirect_uri:
                try:
                    redirect = urlsplit(self.google_analytics_redirect_uri)
                    valid_redirect = (redirect.scheme == "https" and bool(redirect.hostname) and
                                      not redirect.username and not redirect.password and not redirect.fragment and
                                      (redirect.port is None or 1 <= redirect.port <= 65535))
                except ValueError:
                    valid_redirect = False
                if not valid_redirect:
                    raise ValueError("Dashboard OAuth redirect URI must be a valid HTTPS URL without credentials or fragment")
            if self.app_host in {"0.0.0.0", "::"}:
                raise ValueError("In lab, bind to a private interface behind TLS and a firewall")
            return
        capture_token = self.capture_api_token or (self.lab_api_token if self.app_env.lower() == "local" else None)
        if capture_token is None or len(capture_token.get_secret_value()) < 24:
            raise ValueError("CAPTURE_API_TOKEN must contain at least 24 characters")
        if self.operator_read_token and len(self.operator_read_token.get_secret_value()) < 24:
            raise ValueError("OPERATOR_READ_TOKEN must contain at least 24 characters")
        if (capture_token and self.operator_read_token and
                capture_token.get_secret_value() == self.operator_read_token.get_secret_value()):
            raise ValueError("Capture and operator tokens must be different")


@lru_cache
def get_settings() -> Settings:
    return Settings()
