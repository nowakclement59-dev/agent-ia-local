"""Noyau modulaire de l'agent IA local."""

from agent.config import (
    MAX_STEPS,
    NUM_CTX,
    NUM_PREDICT,
    OLLAMA_URL,
    PREFERRED_MODELS,
    REPEAT_PENALTY,
    TEMPERATURE,
    build_system_prompt,
    get_installed_models,
    load_dotenv,
    select_default_model,
)
from agent.context import ConversationContext, WorkspaceState
from agent.loop import AgentLoop
from agent.swarm import DEFAULT_WORKERS, SwarmManager, WorkerProfile

__all__ = [
    "AgentLoop",
    "ConversationContext",
    "DEFAULT_WORKERS",
    "MAX_STEPS",
    "NUM_CTX",
    "NUM_PREDICT",
    "OLLAMA_URL",
    "PREFERRED_MODELS",
    "REPEAT_PENALTY",
    "SwarmManager",
    "TEMPERATURE",
    "WorkerProfile",
    "WorkspaceState",
    "build_system_prompt",
    "get_installed_models",
    "load_dotenv",
    "select_default_model",
]
