"""Constrói o `ChannelAdapter` certo a partir de uma linha de `channels`.

`credentials_encrypted` guarda um JSON cifrado como valor único (campos
variam por provedor — ver `docs/03-modelo-de-dados.md` §1); decifrar e
desserializar aqui é o único lugar do sistema que conhece esse formato.
"""

import json

from app.channels.base import ChannelAdapter
from app.channels.evolution import EvolutionAdapter
from app.channels.meta_cloud import MetaCloudAdapter
from app.core.errors import ExternalServiceError
from app.models import Channel


def build_adapter(channel: Channel) -> ChannelAdapter:
    if not channel.credentials_encrypted:
        raise ExternalServiceError(f"Canal {channel.id} sem credenciais configuradas.")
    credenciais = json.loads(channel.credentials_encrypted)
    webhook_verify_token = channel.webhook_verify_token_encrypted or ""

    if channel.provider == "evolution":
        return EvolutionAdapter(
            base_url=credenciais["base_url"],
            api_key=credenciais["api_key"],
            instance_name=credenciais["instance_name"],
            webhook_verify_token=webhook_verify_token,
            capabilities=channel.capabilities,
        )
    if channel.provider == "meta_cloud":
        return MetaCloudAdapter(
            access_token=credenciais["access_token"],
            phone_number_id=credenciais["phone_number_id"],
            app_secret=credenciais["app_secret"],
            webhook_verify_token=webhook_verify_token,
            capabilities=channel.capabilities,
            api_version=credenciais.get("api_version", "v21.0"),
        )
    raise ExternalServiceError(f"Provedor de canal desconhecido: {channel.provider}")
