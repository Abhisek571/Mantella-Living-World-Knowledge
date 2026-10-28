"""Mantella Living World - Knowledge: per-NPC knowledge levels, secrets and lore lookup."""
from . import knowledge  # noqa: F401
from . import hookup


def register(api):
    """Hooks for Mantella - Direct AI Connect: cached knowledge in the system prompt, lore lines per reply."""
    api.on('system_parts', hookup.system_parts)
    api.on('extra_user_text', hookup.extra_user_text)
