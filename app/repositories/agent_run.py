"""Repositório de `agent_runs` — `docs/03-modelo-de-dados.md` §5.

Um registro por turno processado por `app/agent/runtime.py` (roadmap 3.4):
base do custo e da depuração do agente.
"""

from app.models import AgentRun
from app.repositories.base import BaseRepository


class AgentRunRepository(BaseRepository[AgentRun]):
    model = AgentRun
