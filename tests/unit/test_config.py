import os

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_settings_loads_from_env() -> None:
    settings = Settings()  # type: ignore[call-arg]

    assert settings.app_name == "sdr-agent"
    assert settings.database_url.startswith("postgresql+asyncpg://")


def test_settings_fails_clearly_without_required_var() -> None:
    valor_original = os.environ.pop("APP_ENCRYPTION_KEY")
    try:
        with pytest.raises(ValidationError) as exc_info:
            Settings(_env_file=None)  # type: ignore[call-arg]
        assert "app_encryption_key" in str(exc_info.value).lower()
    finally:
        os.environ["APP_ENCRYPTION_KEY"] = valor_original
