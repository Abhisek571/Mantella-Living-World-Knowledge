"""The World Knowledge page in Mantella's settings UI: knowledge packs and their entries, turned on and off, written,
imported and exported. Built with Mantella's Gradio (4.28); every value is read again on each page load."""
import html
import json
import os

from . import hookup
from . import world_knowledge as WK

PACK_HEADERS = ['Pack', 'Id', 'Source', 'Entries', 'On', 'Problems']
ENTRY_HEADERS = ['Entry', 'On', 'Mode', 'Text', 'Conditions', 'Problems']
EXPORT_DIR = os.path.join('data', 'living_world', 'knowledge_pack_exports')
NEW_ENTRY = ''
INTRO = ('Facts bigger than one NPC that only some NPCs know.',
         'A knowledge pack is a list of facts, each with conditions saying who knows it. "Always" facts go into the '
         'prompt of every NPC who meets the conditions; "relevant" facts only into the reply where the player talks '
         'about them. Packs you make here are yours to edit; packs a mod ships can be turned on and off, as a whole or '
         'fact by fact. Changes apply from the next reply.')
CONDITIONS_HELP = ('Who knows it. Empty: everyone. Join with and, or, not and brackets, e.g. '
                   '"hold: Whiterun and (faction: Companions or group: Riverwood folk)".\n'
                   'location: Riverwood (there now, or lives there)\nhold: The Rift (lives in or is in)\n'
                   'faction: Companions (also College of Winterhold, Thieves Guild, Dark Brotherhood, Greybeards, Blades, '
                   'Thalmor, Legion, Stormcloaks, a vanilla job such as innkeeper, guard, follower; any other faction as '
                   'Plugin.esp|0xFormID)\ngroup: a named group of this pack\n'
                   'quest: MQ104 >= 90, quest: MQ104 <= 160, quest: MQ104 done\n'
                   'global: Skyrim.esm|0x000039 >= 30\n'
                   'Factions by form id, globals and quests are read in game by the Knowledge plugin when an NPC joins a talk.')
MODE_HELP = 'Always: in the prompt whenever the conditions pass. Relevant: only when the player\'s line mentions its keywords.'
KEYWORDS_HELP = 'For relevant facts, comma separated. Empty: the names in the text are used.'
GROUPS_HELP = 'One group per line: "Group name: Name, Name, 0001347B" (NPC names or base ids). Used by "group:" conditions.'
BUDGET_HELP = (f'The most tokens of "always" facts in one prompt ({WK.MAX_BUDGET} at most). Relevant facts share the '
               'Lore per reply budget of the Settings tab and come before lore.')


def _tip(text: str) -> str:
    # the markup Mantella's own settings use for the "?" icon (its style.css shows the text on hover)
    return ('<div class="tooltip-container" role="tooltip"><span class="tooltip-icon" tabindex="0">?</span>'
            '<div class="tooltip-content-left" style="max-width:min(420px,80vw);white-space:normal">'
            f'<p>{html.escape(text).replace(chr(10), "<br>")}</p></div></div>')


def _heading(title: str, text: str, about: str = '') -> str:
    line = f'<p style="margin:2px 0 8px;opacity:.8">{html.escape(about)}</p>' if about else ''
    return f'<h2 style="display:flex;align-items:center;gap:6px;margin:18px 0 2px">{html.escape(title)}{_tip(text)}</h2>{line}'


def _intro(text: str, help_text: str) -> str:
    return (f'<div style="display:flex;align-items:center;gap:6px;margin:4px 0 10px;opacity:.85">'
            f'{html.escape(text)}{_tip(help_text)}</div>')


def _confirm_js(question: str) -> str:
    # the browser's own "are you sure?" box; the hidden checkbox is the first input and gets the answer
    return "(...a) => { a[0] = confirm(" + json.dumps(question) + "); return a; }"


def _notify(gr, text: str) -> str:
    try:
        gr.Info(text)
    except Exception:  # noqa: BLE001
        pass
    return text


def _short(text: str, limit: int = 70) -> str:
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def pack_rows(packs, state) -> list[list]:
    return [[p['name'], p['id'], p['source'], len(p['entries']), 'Yes' if WK.pack_on(p, state) else 'No',
             '; '.join(p['problems'] + [f"{sum(1 for e in p['entries'] if e['problems'])} entries with problems"]
                       if any(e['problems'] for e in p['entries']) else p['problems'])] for p in packs]


def entry_rows(pack, state) -> list[list]:
    if not pack:
        return []
    return [[e['id'], 'Yes' if WK.entry_on(pack, e, state) else 'No', e['mode'], _short(e['text']),
             WK.conditions_text(e['conditions']) if e['conditions'] else '(everyone)', '; '.join(e['problems'])]
            for e in pack['entries']]


def pack_choices(packs) -> list[tuple[str, str]]:
    return [(f"{p['name']} ({p['id']})", p['id']) for p in packs]


def entry_choices(pack) -> list[tuple[str, str]]:
    first = [('New entry', NEW_ENTRY)] if pack and WK.editable(pack) else []
    return first + [(f"{e['id']}: {_short(e['text'], 50)}", e['id']) for e in (pack or {}).get('entries', [])]


def editor_values(pack, entry_id, state=None) -> tuple:
    """(text, mode, keywords, conditions, on) for the editor."""
    entry = next((e for e in (pack or {}).get('entries', []) if e['id'] == entry_id), None)
    if not entry:
        return '', 'always', '', '', True
    raw = entry.get('conditions_raw')
    cond = WK.conditions_text(entry['conditions']) if entry['conditions'] else (raw if isinstance(raw, str) else '')
    on = WK.entry_on(pack, entry, state) if state else entry['enabled']
    return entry['text'], entry['mode'] if entry['mode'] in WK.MODES else 'always', ', '.join(entry['keywords']), cond, on


def pack_note(pack) -> str:
    """One line under the pick: whose pack it is and what can be changed."""
    if not pack:
        return 'No knowledge packs yet. Make one under "New pack", or import one.'
    if WK.editable(pack):
        return f"**{pack['name']}** is your own pack: add, change and delete its facts and groups here."
    who = f" by {pack['author']}" if pack['author'] else ''
    return (f"**{pack['name']}** comes from {pack['source']}{who}: turn it, or single facts, on and off here. "
            "To change a fact, write your own version in a pack of yours and turn this one off.")


def checks_note(packs, state) -> str:
    """Which conditions need the game side, in plain words."""
    checks = WK.game_checks(packs, state)
    lists = checks['stringList']
    count = len(lists['quests']) + len(lists['global_keys']) + len(lists['faction_keys'])
    if not count:
        return ''
    return (f"{count} quest, global or faction check(s) are read in game by the Knowledge plugin when an NPC joins a "
            "talk. Until then, or without the plugin, those conditions count as not met.")


def first_entry(pack) -> str:
    """The fact picked when a pack is opened: New entry in the player's own pack, else its first fact."""
    if not pack or WK.editable(pack) or not pack['entries']:
        return NEW_ENTRY
    return pack['entries'][0]['id']


def build(gr, packs_dir=None, state_path=None, export_dir=None) -> None:
    """The page's content (inside a tab the caller made)."""
    packs_dir = packs_dir or WK.PACKS_DIR
    export_dir = export_dir or EXPORT_DIR
    load = lambda: WK.load_packs(packs_dir)
    state = lambda: WK.load_state(state_path)

    def refresh_checks():
        try:
            WK.write_checks(hookup.CHANNEL_DIR, load(), state())
        except OSError:
            pass

    def view(pack_id=None, entry_id=NEW_ENTRY, message=''):
        packs, st = load(), state()
        pack = WK.find_pack(packs, pack_id) or (packs[0] if packs else None)
        if entry_id not in [e['id'] for e in (pack or {}).get('entries', [])]:
            entry_id = first_entry(pack)
        notes = [pack_note(pack), checks_note(packs, st), message]
        return (pack_rows(packs, st), gr.update(choices=pack_choices(packs), value=pack['id'] if pack else None),
                entry_rows(pack, st), gr.update(choices=entry_choices(pack), value=entry_id),
                *editor_values(pack, entry_id, st), WK.groups_text(pack['groups']) if pack else '',
                '\n\n'.join(n for n in notes if n))

    gr.HTML(_intro(*INTRO))
    gr.HTML(_heading('Knowledge packs', 'Every JSON file in data/living_world/knowledge_packs. Mods can ship packs '
                     'there. A pack that is off adds nothing.', 'Pick a pack to see and change its facts.'))
    packs_table = gr.Dataframe(headers=PACK_HEADERS, value=lambda: pack_rows(load(), state()), interactive=False, height=240)
    first = lambda: (load()[0]['id'] if load() else None)
    first_pack = lambda: WK.find_pack(load(), first())
    with gr.Row(equal_height=False):
        pack_pick = gr.Dropdown(choices=pack_choices(load()), value=first, label='Pack')
        toggle_pack = gr.Button('Turn pack on/off', scale=0, min_width=160)
        export = gr.Button('Export pack', scale=0, min_width=140)
        delete_pack = gr.Button('Delete pack', scale=0, min_width=140, elem_classes=['lw-danger'])
    said = gr.Markdown(lambda: '\n\n'.join(n for n in (pack_note(first_pack()), checks_note(load(), state())) if n))
    export_file = gr.File(label='Exported pack', interactive=False, visible=False)
    with gr.Accordion('New pack', open=False):
        with gr.Row(equal_height=False):
            new_name = gr.Textbox(label='Name', placeholder='e.g. Riverwood news')
            create = gr.Button('Make pack', variant='primary', scale=0, min_width=140)
    with gr.Accordion('Import a pack', open=False):
        import_file = gr.File(label='Knowledge pack (.json)', file_types=['.json'], type='filepath')
        do_import = gr.Button('Import', scale=0, min_width=140)

    gr.HTML(_heading('Facts', 'The facts of the picked pack. A fact with problems is never used; the Problems column '
                     'says why.', 'Pick a fact to change it, or "New entry" to add one to your own pack.'))
    entries_table = gr.Dataframe(headers=ENTRY_HEADERS, value=lambda: entry_rows(first_pack(), state()), interactive=False, height=360)
    entry_pick = gr.Dropdown(choices=entry_choices(first_pack()), value=lambda: first_entry(first_pack()), label='Fact')
    text = gr.Textbox(label='Text', lines=3, info='What the NPCs who meet the conditions know, as a plain statement.')
    with gr.Row(equal_height=False):
        mode = gr.Radio(choices=list(WK.MODES), value='always', label='Mode', info=MODE_HELP)
        enabled = gr.Checkbox(value=True, label='On')
    keywords = gr.Textbox(label='Keywords', info=KEYWORDS_HELP)
    conditions = gr.Textbox(label='Conditions', lines=2, info=CONDITIONS_HELP.split('\n')[0])
    gr.HTML(f'<div style="opacity:.8;font-size:.9em;white-space:pre-line;margin:-4px 0 8px">'
            f'{html.escape(chr(10).join(CONDITIONS_HELP.split(chr(10))[1:]))}</div>')
    with gr.Row():
        save_entry = gr.Button('Save fact', variant='primary', scale=0, min_width=140)
        toggle_entry = gr.Button('Turn fact on/off', scale=0, min_width=160)
        delete_entry = gr.Button('Delete fact', scale=0, min_width=140, elem_classes=['lw-danger'])
    with gr.Accordion('Named groups of this pack', open=False):
        groups = gr.Textbox(label='Groups', lines=4, info=GROUPS_HELP)
        save_groups = gr.Button('Save groups', scale=0, min_width=140)
    with gr.Accordion('Budget', open=False):
        budget = gr.Number(value=lambda: state()['budget'], label='"Always" facts per prompt (tokens)', info=BUDGET_HELP,
                           precision=0, minimum=0)
        save_budget = gr.Button('Save budget', scale=0, min_width=140)
    sure = gr.Checkbox(visible=False)

    outs = [packs_table, pack_pick, entries_table, entry_pick, text, mode, keywords, conditions, enabled, groups, said]

    def picked_entry(pack_id, entry_id):
        return editor_values(WK.find_pack(load(), pack_id), entry_id, state())

    def flip_pack(pack_id):
        pack = WK.find_pack(load(), pack_id)
        if not pack:
            return view(None, NEW_ENTRY, 'Pick a pack first.')
        on = not WK.pack_on(pack, state())
        WK.set_pack_on(pack, on, state_path)
        refresh_checks()
        return view(pack_id, NEW_ENTRY, _notify(gr, f"{pack['name']} is {'on' if on else 'off'}."))

    def make_pack(name):
        pack = WK.new_pack(name, packs_dir)
        return view(pack['id'], NEW_ENTRY, _notify(gr, f"Made {pack['name']}. Add its first fact below."))

    def save_fact(pack_id, entry_id, t, m, k, c, on):
        pack = WK.find_pack(load(), pack_id)
        if not pack:
            return view(None, NEW_ENTRY, 'Make a pack first.')
        if not WK.editable(pack):
            entry = next((e for e in pack['entries'] if e['id'] == entry_id), None)
            if entry:
                WK.set_entry_on(pack, entry_id, bool(on), state_path)
                refresh_checks()
            return view(pack_id, entry_id, 'Only On is kept for a mod\'s fact.' if entry else 'Pick a fact.')
        new_id, problems = WK.save_entry(pack, entry_id or None, t, m, k, c, on, packs_dir)
        if problems:  # the editor keeps what was typed, so it can be fixed
            shown = list(view(pack_id, entry_id, 'Not saved: ' + '; '.join(problems)))
            shown[4:9] = [t, m, k, c, on]
            return tuple(shown)
        refresh_checks()
        return view(pack_id, new_id, _notify(gr, 'Saved. Used from the next reply.'))

    def flip_fact(pack_id, entry_id):
        pack = WK.find_pack(load(), pack_id)
        entry = next((e for e in (pack or {}).get('entries', []) if e['id'] == entry_id), None)
        if not entry:
            return view(pack_id, entry_id, 'Pick a fact first.')
        on = not WK.entry_on(pack, entry, state())
        WK.set_entry_on(pack, entry_id, on, state_path)
        refresh_checks()
        return view(pack_id, entry_id, _notify(gr, f"Fact {entry_id} is {'on' if on else 'off'}."))

    def remove_fact(ok, pack_id, entry_id):
        pack = WK.find_pack(load(), pack_id)
        if not ok:
            return view(pack_id, entry_id, 'Not deleted.')
        if not pack or not WK.delete_entry(pack, entry_id, packs_dir):
            return view(pack_id, entry_id, 'Only facts of your own packs can be deleted; turn a mod\'s fact off instead.')
        refresh_checks()
        return view(pack_id, NEW_ENTRY, _notify(gr, f'Deleted fact {entry_id}.'))

    def store_groups(pack_id, value):
        pack = WK.find_pack(load(), pack_id)
        if not pack or not WK.save_groups(pack, value, packs_dir):
            return view(pack_id, NEW_ENTRY, 'Groups are only changed in your own packs.')
        return view(pack_id, NEW_ENTRY, _notify(gr, 'Groups saved.'))

    def remove_pack(ok, pack_id):
        pack = WK.find_pack(load(), pack_id)
        if not ok:
            return view(pack_id, NEW_ENTRY, 'Not deleted.')
        moved = WK.delete_pack(pack, packs_dir) if pack else None
        if not moved:
            return view(pack_id, NEW_ENTRY, 'A mod\'s pack is not deleted here: turn it off, or remove the mod.')
        refresh_checks()
        return view(None, NEW_ENTRY, _notify(gr, f"Deleted {pack['name']}; the file was moved to {moved}."))

    def export_one(pack_id):
        pack = WK.find_pack(load(), pack_id)
        if not pack:
            return gr.update(visible=False), 'Pick a pack first.'
        path = WK.export_pack(pack, export_dir, state_path)
        return gr.update(value=path, visible=True), _notify(gr, f'Exported to {path}. Download it below, or find it there.')

    def import_one(path):
        if not path:
            return view(None, NEW_ENTRY, 'Choose a pack file first.')
        pack, message = WK.import_pack(path, packs_dir)
        refresh_checks()
        return view(pack['id'] if pack else None, NEW_ENTRY, _notify(gr, message) if pack else message)

    def store_budget(value):
        return _notify(gr, f'"Always" facts may use up to {WK.set_budget(value, state_path)} tokens per prompt.')

    # the pick itself is left out of its own outputs, so filling it never fires its change again
    pack_pick.change(lambda p: (lambda v: v[:1] + v[2:])(view(p)), inputs=[pack_pick], outputs=[o for o in outs if o is not pack_pick])
    entry_pick.change(picked_entry, inputs=[pack_pick, entry_pick], outputs=[text, mode, keywords, conditions, enabled])
    toggle_pack.click(flip_pack, inputs=[pack_pick], outputs=outs)
    create.click(make_pack, inputs=[new_name], outputs=outs)
    save_entry.click(save_fact, inputs=[pack_pick, entry_pick, text, mode, keywords, conditions, enabled], outputs=outs)
    toggle_entry.click(flip_fact, inputs=[pack_pick, entry_pick], outputs=outs)
    delete_entry.click(remove_fact, inputs=[sure, pack_pick, entry_pick], outputs=outs,
                       js=_confirm_js('Delete this fact from your pack?'))
    save_groups.click(store_groups, inputs=[pack_pick, groups], outputs=outs)
    delete_pack.click(remove_pack, inputs=[sure, pack_pick], outputs=outs,
                      js=_confirm_js('Delete this pack? Its file is moved to data/living_world/knowledge_packs_deleted.'))
    # events that touch a File stay out of the API listing: Gradio 4.28 cannot describe a File there
    export.click(export_one, inputs=[pack_pick], outputs=[export_file, said], show_api=False)
    do_import.click(import_one, inputs=[import_file], outputs=outs, show_api=False)
    save_budget.click(store_budget, inputs=[budget], outputs=[said])


def build_page(gr, config=None) -> None:
    """A "World Knowledge" tab of its own (Mantella exes with tabs of their own)."""
    with gr.Tab('World Knowledge'):
        build(gr)


def build_section(gr) -> None:
    """The same page as a section of the Living World tab (an older Mantella exe without tabs of their own)."""
    with gr.Accordion('World Knowledge', open=False):
        build(gr)
