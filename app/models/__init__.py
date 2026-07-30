"""Registro central de models — importar aqui garante que `Base.metadata`
enxergue toda tabela no autogenerate do Alembic (`alembic/env.py`)."""

from app.models.agent_run import AgentRun
from app.models.appointment import Appointment
from app.models.audit_log import AuditLog
from app.models.base import Base
from app.models.channel import Channel
from app.models.consent import Consent
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.crm_sync_log import CrmSyncLog
from app.models.followup import Followup
from app.models.handoff import Handoff
from app.models.knowledge import FaqEntry, KnowledgeChunk, KnowledgeDocument
from app.models.message import Message, MessageTemplate
from app.models.qualification import Qualification
from app.models.seller import Seller
from app.models.tenant import Tenant, TenantConfig
from app.models.user import User
from app.models.webhook_event import WebhookEvent

__all__ = [
    "AgentRun",
    "Appointment",
    "AuditLog",
    "Base",
    "Channel",
    "Consent",
    "Contact",
    "Conversation",
    "CrmSyncLog",
    "FaqEntry",
    "Followup",
    "Handoff",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "Message",
    "MessageTemplate",
    "Qualification",
    "Seller",
    "Tenant",
    "TenantConfig",
    "User",
    "WebhookEvent",
]
