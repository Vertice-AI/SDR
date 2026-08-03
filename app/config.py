"""Configuração da aplicação via pydantic-settings.

Falha rápido e com mensagem clara na inicialização se faltar variável
obrigatória — não deixamos o processo subir "quase configurado".
"""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Aplicação
    app_env: Literal["local", "staging", "production"] = "local"
    app_name: str = "sdr-agent"
    app_base_url: str = "http://localhost:8000"
    app_secret_key: str
    app_encryption_key: str
    phone_hash_pepper: str
    log_level: str = "INFO"
    default_timezone: str = "America/Sao_Paulo"

    # Banco e fila
    database_url: str
    # Só para Alembic: role com privilégio para ALTER TABLE / CREATE POLICY /
    # GRANT. A aplicação em runtime nunca usa esta URL (`docs/03` §6).
    # Vazio = usa `database_url` (ambientes sem role separada ainda).
    database_admin_url: str = ""
    redis_url: str = "redis://localhost:6379/0"

    # LLM
    anthropic_api_key: str
    llm_model_main: str = "claude-sonnet-5"
    llm_model_fast: str = "claude-haiku-4-5-20251001"
    llm_max_iterations: int = 6
    llm_timeout_seconds: int = 20
    tool_timeout_seconds: int = 10

    # Embeddings
    embedding_provider: Literal["voyage", "openai"] = "voyage"
    embedding_model: str = "voyage-3"
    embedding_dimensions: int = 1024
    voyage_api_key: str = ""
    openai_api_key: str = ""

    # Transcrição de áudio
    transcription_provider: Literal["openai", "deepgram", "none"] = "none"
    deepgram_api_key: str = ""

    # Google Calendar
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/admin/integrations/google/callback"

    # Conversa
    default_debounce_seconds: int = 8
    max_debounce_seconds: int = 30
    conversation_lock_ttl_seconds: int = 120
    max_messages_in_context: int = 20
    summarize_every_n_messages: int = 15
    slot_reservation_ttl_seconds: int = 600

    # Observabilidade
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    sentry_dsn: str = ""
    prometheus_enabled: bool = True

    # Alertas
    alert_webhook_url: str = ""
    alert_min_severity: Literal["low", "medium", "high", "critical"] = "high"

    # Evolution API (apenas dev/homologação)
    evolution_base_url: str = "http://localhost:8080"
    evolution_api_key: str = ""

    @field_validator("app_encryption_key")
    @classmethod
    def _validar_chave_criptografia(cls, valor: str) -> str:
        if not valor:
            raise ValueError(
                "APP_ENCRYPTION_KEY é obrigatória — gere 32 bytes em base64 "
                '(python -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())")'
            )
        return valor


@lru_cache
def get_settings() -> Settings:
    return Settings()
