"""Mantella Living World - Knowledge: per-NPC knowledge levels, secrets, lore lookup and world knowledge packs."""
import sys

from . import knowledge  # noqa: F401
from . import hookup
from . import world_knowledge_ui


def _hub_tab():
    """The Integration Hub's tab module when it is loaded and can take a page of another module (Mantella loads the
    extensions in name order, so living_world comes before lw_knowledge); None otherwise."""
    parent = __name__.rpartition('.')[0]
    tab = sys.modules.get((parent + '.' if parent else '') + 'living_world.ui_tab')
    return tab if callable(getattr(tab, 'add_page', None)) else None


def register(api):
    """Hooks for Mantella - Direct AI Connect: cached knowledge in the system prompt, lore lines per reply, and the
    World Knowledge page."""
    api.on('system_parts', hookup.system_parts)
    api.on('extra_user_text', hookup.extra_user_text)
    # the game reads the check list when an NPC joins, before any prompt is built: a pack turned on since the
    # last session must be in it for its first talk
    hookup.write_checks()
    hub = _hub_tab()
    if hub is not None:  # a page inside the Living World tab, next to the Hub's own
        hub.add_page('World Knowledge', world_knowledge_ui.build)
        return
    try:  # an older Hub: a tab of its own
        api.on('ui_page', lambda gr, config: world_knowledge_ui.build_page(gr, config))
    except ValueError:  # an older Mantella exe without tabs of their own: a section of its Living World tab
        api.on('ui_tab', world_knowledge_ui.build_section)
