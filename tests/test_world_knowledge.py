"""World knowledge packs: parsing, conditions, selection within the budget, the game side's check list, the hooks into
the prompt and the World Knowledge page (with a stand-in for Gradio)."""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

import lw_knowledge  # noqa: E402
from lw_knowledge import hookup as H  # noqa: E402
from lw_knowledge import world_knowledge as WK  # noqa: E402
from lw_knowledge import world_knowledge_ui as UI  # noqa: E402

NO_GAME = {'stages': {}, 'done': {}, 'globals': {}, 'factions': {}}


def npc(name="Hulda", base="013BA3", **file):
    return WK.npc_view(base, dict(name=name, **file), None)


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


class Conditions(unittest.TestCase):
    def test_text_round_trip(self):
        for text in ("hold: Whiterun",
                     "hold: Whiterun and (faction: Companions or group: Riverwood folk)",
                     "not faction: Thalmor",
                     "quest: MQ104 >= 90 and quest: MQ106 done",
                     "global: Skyrim.esm|0x000039 >= 30",
                     'group: "Hunters and Trappers"'):
            cond = WK.parse_conditions(text)
            self.assertEqual(WK.parse_conditions(WK.conditions_text(cond)), cond, text)

    def test_and_binds_tighter_than_or(self):
        cond = WK.parse_conditions("hold: Rift or hold: Reach and faction: Thalmor")
        self.assertEqual(cond, {'any': [{'hold': 'Rift'}, {'all': [{'hold': 'Reach'}, {'faction': 'Thalmor'}]}]})

    def test_quest_forms(self):
        self.assertEqual(WK.parse_conditions("quest: MQ104 > 90"), {'quest': 'MQ104', 'stage_min': 91})
        self.assertEqual(WK.parse_conditions("quest: MQ104 = 90"), {'quest': 'MQ104', 'stage_min': 90, 'stage_max': 90})
        self.assertEqual(WK.parse_conditions("quest: MQ104 not done"), {'quest': 'MQ104', 'completed': False})

    def test_bad_text_says_why(self):
        for text in ("hold Whiterun", "weather: rain", "hold: Whiterun faction: Thalmor", "(hold: Rift",
                     "global: GameDaysPassed >= 3", "faction: Skyrim|12", "quest: MQ104 maybe", "hold:"):
            with self.assertRaises(WK.ConditionError, msg=text):
                WK.parse_conditions(text)

    def test_json_conditions_checked(self):
        cond = WK.check_conditions([{"hold": "Rift"}, {"any": [{"faction": "Thieves Guild"}, {"group": "Fences"}]}])
        self.assertEqual(cond, {'all': [{'hold': 'Rift'}, {'any': [{'faction': 'Thieves Guild'}, {'group': 'Fences'}]}]})
        self.assertIsNone(WK.check_conditions(""))
        with self.assertRaises(WK.ConditionError):
            WK.check_conditions({"global": "Skyrim.esm|0x39", "op": "~", "value": 1})
        with self.assertRaises(WK.ConditionError):
            WK.check_conditions({"weather": "rain"})

    def test_form_key(self):
        self.assertEqual(WK.form_key("Skyrim.esm|0x048362"), "skyrim.esm|048362")
        self.assertEqual(WK.form_key("My Mod.esp | FE000801"), "my mod.esp|000801")
        self.assertIsNone(WK.form_key("Companions"))

    def test_missing_game_data_never_passes_under_not(self):
        # not checked yet by the game: an excluded NPC must not get the fact (and nobody else gets it on a guess either)
        thalmor = WK.parse_conditions("not faction: Skyrim.esm|0x039F26")
        self.assertFalse(WK.passes(thalmor, npc(), NO_GAME, {}))
        self.assertTrue(WK.passes(thalmor, npc(), dict(NO_GAME, factions={0x013BA3: set()}), {}))
        self.assertFalse(WK.passes(thalmor, npc(), dict(NO_GAME, factions={0x013BA3: {"skyrim.esm|039f26"}}), {}))
        never_done = {'not': {'quest': 'mq106', 'completed': True}}
        self.assertFalse(WK.passes(never_done, npc(), NO_GAME, {}))
        self.assertTrue(WK.passes(never_done, npc(), dict(NO_GAME, done={'mq106': False}), {}))
        # "any" with a known true branch still passes
        self.assertTrue(WK.passes({'any': [{'hold': 'Whiterun'}, never_done]}, npc(hold="Whiterun"), NO_GAME, {}))

    def test_location_and_hold(self):
        here = npc(location="Riverwood", hold="Whiterun", here_hold="Whiterun")
        self.assertTrue(WK.passes({'location': 'riverwood'}, here, NO_GAME, {}))
        self.assertTrue(WK.passes({'hold': 'Whiterun Hold'}, here, NO_GAME, {}))
        self.assertFalse(WK.passes({'hold': 'The Rift'}, here, NO_GAME, {}))
        # visiting the Rift counts as being in it; a home hold from the profile counts too
        visitor = WK.npc_view("1", {"name": "A", "hold": "Whiterun", "here_hold": "Rift"}, {"home": "Riverwood", "hold": "Whiterun Hold"})
        self.assertTrue(WK.passes({'hold': 'the rift'}, visitor, NO_GAME, {}))
        self.assertTrue(WK.passes({'location': 'Riverwood'}, visitor, NO_GAME, {}))

    def test_faction_from_npc_file_and_game(self):
        member = npc(groups=["Companions"], work="blacksmith", guard=1)
        self.assertTrue(WK.passes({'faction': 'companions'}, member, NO_GAME, {}))
        self.assertTrue(WK.passes({'faction': 'Blacksmith'}, member, NO_GAME, {}))
        self.assertTrue(WK.passes({'faction': 'guard'}, member, NO_GAME, {}))
        self.assertFalse(WK.passes({'faction': 'Thalmor'}, member, NO_GAME, {}))
        cond = {'faction': 'Skyrim.esm|0x01BDB3'}
        self.assertFalse(WK.passes(cond, member, NO_GAME, {}))  # not read in game yet: not met
        game = WK.game_state({"stringList": {"factions:013BA3": ["skyrim.esm|01bdb3"]}})
        self.assertTrue(WK.passes(cond, member, game, {}))

    def test_group_by_name_or_base_id(self):
        packs = [WK.parse_pack({"id": "p", "groups": {"Riverwood folk": ["Lucan Valerius", "0001347B"]}, "entries": []}, "p")]
        groups = WK.all_groups(packs, WK.load_state(os.devnull))
        self.assertTrue(WK.passes({'group': 'riverwood folk'}, npc("Lucan Valerius", "01347C"), NO_GAME, groups, 'p'))
        self.assertTrue(WK.passes({'group': 'Riverwood folk'}, npc("Camilla Valerius", "01347B"), NO_GAME, groups, 'p'))
        self.assertFalse(WK.passes({'group': 'Riverwood folk'}, npc("Hulda"), NO_GAME, groups, 'p'))

    def test_quest_and_global_from_game_and_world(self):
        world = {"quests": {"MQ104": 90}, "quest_state": {"MQ104": 1, "MQ103": 2}}
        game = WK.game_state({"int": {"stage:dlc1vq01": 20, "done:dlc1vq01": 0}, "float": {"global:skyrim.esm|000039": 31.0}}, world)
        n = npc()
        self.assertTrue(WK.passes(WK.parse_conditions("quest: MQ104 >= 90"), n, game, {}))
        self.assertFalse(WK.passes(WK.parse_conditions("quest: MQ104 >= 100"), n, game, {}))
        self.assertTrue(WK.passes(WK.parse_conditions("quest: MQ103 done"), n, game, {}))
        self.assertTrue(WK.passes(WK.parse_conditions("quest: DLC1VQ01 <= 20 and quest: DLC1VQ01 not done"), n, game, {}))
        self.assertFalse(WK.passes(WK.parse_conditions("quest: MS13 >= 1"), n, game, {}))  # unknown quest: not met
        self.assertTrue(WK.passes(WK.parse_conditions("global: Skyrim.esm|0x39 > 30"), n, game, {}))
        self.assertFalse(WK.passes(WK.parse_conditions("global: Skyrim.esm|0x3A > 30"), n, game, {}))

    def test_checked_file_of_another_character_ignored(self):
        game = WK.game_state({"string": {"player": "Other"}, "float": {"global:skyrim.esm|000039": 31.0}}, None, "Player")
        self.assertEqual(game['globals'], {})


class Packs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.packs = os.path.join(self.tmp.name, "knowledge_packs")
        self.state = os.path.join(self.tmp.name, "state.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_marks_problems_and_keeps_good_entries(self):
        pack = WK.parse_pack({"name": "News", "source": "Some Mod", "entries": [
            {"text": "The mill burned.", "conditions": "location: Riverwood"},
            {"text": "", "mode": "always"},
            {"text": "X", "mode": "sometimes"},
            {"text": "Y", "conditions": "weather: rain"}]}, "news")
        self.assertEqual(pack['id'], "news")
        self.assertEqual([bool(e['problems']) for e in pack['entries']], [False, True, True, True])
        self.assertEqual(pack['entries'][0]['source'], "Some Mod")
        self.assertEqual(len(list(WK.active_entries([pack], WK.load_state(self.state)))), 1)
        self.assertTrue(WK.parse_pack("nonsense", "x")['problems'])

    def test_pack_round_trip(self):
        data = {"id": "p", "name": "P", "source": "player", "groups": {"G": ["A"]},
                "entries": [{"id": "a", "text": "T", "mode": "relevant", "keywords": ["mill"],
                             "conditions": "hold: Rift and not faction: Thalmor", "enabled": False}]}
        pack = WK.parse_pack(data, "p")
        again = WK.parse_pack(WK.pack_data(pack), "p")
        self.assertEqual({k: v for k, v in again.items() if k != 'entries'}, {k: v for k, v in pack.items() if k != 'entries'})
        self.assertEqual(again['entries'][0]['conditions'], pack['entries'][0]['conditions'])
        self.assertFalse(again['entries'][0]['enabled'])

    def test_toggles_live_in_the_state_file_not_the_mod_pack(self):
        write(os.path.join(self.packs, "mod.json"), {"source": "Some Mod", "entries": [{"id": "a", "text": "T"}]})
        pack = WK.load_packs(self.packs)[0]
        WK.set_pack_on(pack, False, self.state)
        WK.set_entry_on(pack, "a", False, self.state)
        state = WK.load_state(self.state)
        self.assertFalse(WK.pack_on(pack, state))
        self.assertFalse(WK.entry_on(pack, pack['entries'][0], state))
        with open(os.path.join(self.packs, "mod.json"), encoding="utf-8") as f:
            self.assertNotIn("enabled", json.load(f))
        self.assertEqual(WK.save_entry(pack, "a", "New", "always", "", "", True, self.packs)[0], None)
        self.assertFalse(WK.delete_entry(pack, "a", self.packs))

    def test_player_pack_edit_cycle(self):
        pack = WK.new_pack("Riverwood news", self.packs)
        self.assertEqual(pack['source'], WK.PLAYER_SOURCE)
        eid, problems = WK.save_entry(pack, None, "The mill burned.", "always", "", "location: Riverwood", True, self.packs)
        self.assertEqual(problems, [])
        _, problems = WK.save_entry(WK.load_packs(self.packs)[0], None, "Bad", "always", "", "hold Rift", True, self.packs)
        self.assertTrue(problems)
        pack = WK.load_packs(self.packs)[0]
        self.assertEqual([e['id'] for e in pack['entries']], [eid])
        self.assertTrue(WK.save_groups(pack, "Riverwood folk: Lucan Valerius, 0001347B\nbad line", self.packs))
        pack = WK.load_packs(self.packs)[0]
        self.assertEqual(pack['groups'], {"Riverwood folk": ["Lucan Valerius", "0001347B"]})
        self.assertTrue(WK.delete_entry(pack, eid, self.packs))
        moved = WK.delete_pack(WK.load_packs(self.packs)[0], self.packs, os.path.join(self.tmp.name, "deleted"))
        self.assertTrue(os.path.isfile(moved))
        self.assertEqual(WK.load_packs(self.packs), [])

    def test_export_and_import(self):
        write(os.path.join(self.packs, "mod.json"), {"id": "mod", "source": "Some Mod", "entries": [{"id": "a", "text": "T"}]})
        pack = WK.load_packs(self.packs)[0]
        WK.set_entry_on(pack, "a", False, self.state)
        path = WK.export_pack(pack, os.path.join(self.tmp.name, "out"), self.state)
        with open(path, encoding="utf-8") as f:
            self.assertFalse(json.load(f)['entries'][0]['enabled'])
        imported, message = WK.import_pack(path, self.packs)
        self.assertEqual(imported['id'], "mod_2")  # the id was taken
        self.assertIn("Imported", message)
        self.assertEqual(len(WK.load_packs(self.packs)), 2)
        bad = os.path.join(self.tmp.name, "bad.json")
        write(bad, {"no": "entries"})
        self.assertIsNone(WK.import_pack(bad, self.packs)[0])

    def test_duplicate_pack_id_not_used(self):
        write(os.path.join(self.packs, "a.json"), {"id": "same", "entries": [{"text": "A"}]})
        write(os.path.join(self.packs, "b.json"), {"id": "same", "entries": [{"text": "B"}]})
        used = [e['text'] for _, e in WK.active_entries(WK.load_packs(self.packs), WK.load_state(self.state))]
        self.assertEqual(used, ["A"])

    def test_game_checks_list_only_what_needs_the_game(self):
        write(os.path.join(self.packs, "p.json"), {"entries": [
            {"text": "A", "conditions": "faction: Skyrim.esm|0x01BDB3 and faction: Companions and quest: MQ104 >= 90"},
            {"text": "B", "conditions": "global: Skyrim.esm|0x000039 >= 30"},
            {"text": "C", "conditions": "global: Off.esp|0x800 >= 1", "enabled": False}]})
        packs, state = WK.load_packs(self.packs), WK.load_state(self.state)
        checks = WK.game_checks(packs, state)
        self.assertEqual(checks['stringList']['quests'], ["MQ104"])
        self.assertEqual(checks['stringList']['faction_keys'], ["skyrim.esm|01bdb3"])
        self.assertEqual(checks['stringList']['faction_plugins'], ["skyrim.esm"])
        self.assertEqual(checks['intList']['faction_ids'], [0x01BDB3])
        self.assertEqual(checks['intList']['global_ids'], [0x39])
        channel = os.path.join(self.tmp.name, "channel")
        self.assertFalse(WK.write_checks(channel, packs, state))  # no game folder: nothing written
        os.makedirs(channel)
        self.assertTrue(WK.write_checks(channel, packs, state))
        self.assertFalse(WK.write_checks(channel, packs, state))  # unchanged


class Selection(unittest.TestCase):
    def setUp(self):
        self.state = WK.load_state(os.devnull)
        self.pack = WK.parse_pack({"id": "p", "entries": [
            {"id": "a", "text": "The Riverwood mill's saw broke.", "conditions": "location: Riverwood"},
            {"id": "b", "text": "Companions are hunting a werewolf.", "conditions": "faction: Companions"},
            {"id": "c", "text": "Everyone heard the bells.", "mode": "always"},
            {"id": "r", "text": "A smuggler hides near Halted Stream Camp.", "mode": "relevant", "keywords": ["smuggler"]},
            {"id": "s", "text": "The old Jarl of Falkreath kept wolves.", "mode": "relevant"}]}, "p")
        self.hulda = npc("Hulda", location="Whiterun")
        self.lucan = npc("Lucan Valerius", "01347C", location="Riverwood")
        self.vilkas = npc("Vilkas", "01A694", groups=["Companions"], location="Whiterun")

    def test_always_only_for_npcs_that_pass(self):
        chosen = WK.select([self.pack], self.state, [self.hulda], NO_GAME, 'always', 500)
        self.assertEqual([e['id'] for e, _ in chosen], ["c"])
        chosen = WK.select([self.pack], self.state, [self.lucan, self.vilkas], NO_GAME, 'always', 500)
        self.assertEqual([(e['id'], names) for e, names in chosen],
                         [("a", ["Lucan Valerius"]), ("b", ["Vilkas"]), ("c", ["Lucan Valerius", "Vilkas"])])
        block = WK.system_block(chosen, [self.lucan, self.vilkas])
        self.assertIn("- (Vilkas) Companions are hunting", block)
        self.assertIn("- Everyone heard the bells.", block)  # everyone knows: no names

    def test_budget_respected(self):
        chosen = WK.select([self.pack], self.state, [self.lucan, self.vilkas], NO_GAME, 'always', WK.tokens(self.pack['entries'][0]['text']) + 4)
        self.assertEqual([e['id'] for e, _ in chosen], ["a"])
        self.assertEqual(WK.select([self.pack], self.state, [self.hulda], NO_GAME, 'always', 0), [])

    def test_turned_off_entry_and_pack(self):
        state = {'packs': {}, 'entries': {'p/c': False}, 'budget': 200}
        self.assertEqual(WK.select([self.pack], state, [self.hulda], NO_GAME, 'always', 500), [])
        state = {'packs': {'p': False}, 'entries': {}, 'budget': 200}
        self.assertEqual(WK.select([self.pack], state, [self.lucan], NO_GAME, 'always', 500), [])

    def test_relevant_by_keywords_once_per_talk(self):
        sent = set()
        chosen = WK.select([self.pack], self.state, [self.hulda], NO_GAME, 'relevant', 500, "Seen any SMUGGLERS? A smuggler, maybe?", sent)
        self.assertEqual([e['id'] for e, _ in chosen], ["r"])
        self.assertEqual(WK.select([self.pack], self.state, [self.hulda], NO_GAME, 'relevant', 500, "the smuggler again", sent), [])
        # no keywords: the names in the text ("Jarl", "Falkreath")
        chosen = WK.select([self.pack], self.state, [self.hulda], NO_GAME, 'relevant', 500, "tell me about falkreath")
        self.assertEqual([e['id'] for e, _ in chosen], ["s"])
        self.assertEqual(WK.select([self.pack], self.state, [self.hulda], NO_GAME, 'relevant', 500, "nice weather"), [])
        self.assertEqual(WK.reply_lines(chosen), ["(What Hulda knows about this: The old Jarl of Falkreath kept wolves.)"])

    def test_relevance_hook_replaces_keywords_and_falls_back(self):
        try:
            WK.set_relevance(lambda text, entries: [e for e in entries if e['id'] == 's'])
            chosen = WK.select([self.pack], self.state, [self.hulda], NO_GAME, 'relevant', 500, "who rules the pine forest town?")
            self.assertEqual([e['id'] for e, _ in chosen], ["s"])
            WK.set_relevance(lambda text, entries: 1 / 0)
            chosen = WK.select([self.pack], self.state, [self.hulda], NO_GAME, 'relevant', 500, "a smuggler")
            self.assertEqual([e['id'] for e, _ in chosen], ["r"])
        finally:
            WK.set_relevance(None)


def conversation(tmp, speakers):
    for name, base, extra in speakers:
        write(os.path.join(tmp, "npc", base + ".json"), {"string": dict(name=name, **extra), "int": {}})
    write(os.path.join(tmp, "conversation.json"), {"string": {"player": "Player"}, "stringList": {"speakers": [b for _, b, _ in speakers]}})


class Hooks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = (H.CHANNEL_DIR, WK.PACKS_DIR, WK.STATE_FILE)
        H.CHANNEL_DIR = os.path.join(self.tmp.name, "channel")
        WK.PACKS_DIR = os.path.join(self.tmp.name, "packs")
        WK.STATE_FILE = os.path.join(self.tmp.name, "state.json")
        H.reset()
        write(os.path.join(WK.PACKS_DIR, "news.json"), {"entries": [
            {"text": "The Riverwood mill's saw broke.", "conditions": "location: Riverwood"},
            {"text": "A smuggler hides near Halted Stream Camp.", "mode": "relevant", "keywords": ["smuggler"]},
            {"text": "Thalmor agents watch the roads.", "conditions": "faction: Skyrim.esm|0x039F26"}]})

    def tearDown(self):
        H.CHANNEL_DIR, WK.PACKS_DIR, WK.STATE_FILE = self.old
        self.tmp.cleanup()

    def test_npc_without_profile_gets_world_knowledge(self):
        conversation(H.CHANNEL_DIR, [("Modded Miller", "FE0801", {"location": "Riverwood"})])
        parts = H.system_parts({"background": "Bio.", "__order__": ["background"]}, {})
        self.assertIn("The Riverwood mill's saw broke.", parts.get("knows", ""))
        self.assertNotIn("Thalmor", parts.get("knows", ""))
        self.assertEqual(parts["__order__"], ["background"])
        # the game side's check list was written for the Thalmor faction
        with open(os.path.join(H.CHANNEL_DIR, WK.CHECKS_FILE), encoding="utf-8") as f:
            self.assertEqual(json.load(f)['stringList']['faction_keys'], ["skyrim.esm|039f26"])
        write(os.path.join(H.CHANNEL_DIR, WK.CHECKED_FILE), {"string": {"player": "Player"},
                                                              "stringList": {"factions:FE0801": ["skyrim.esm|039f26"]}})
        self.assertIn("Thalmor agents", H.system_parts({"background": "Bio."}, {}).get("knows", ""))

    def test_world_knowledge_added_after_npc_knows_block(self):
        conversation(H.CHANNEL_DIR, [("Camilla Valerius", "01347B", {"location": "Riverwood"})])
        parts = H.system_parts({"background": "Bio."}, {})
        self.assertIn("Camilla Valerius", parts.get("identity", ""))
        self.assertTrue(parts["knows"].rstrip().endswith("The Riverwood mill's saw broke."))

    def test_relevant_entry_in_newest_message_and_off_mode(self):
        conversation(H.CHANNEL_DIR, [("Modded Miller", "FE0801", {"location": "Whiterun"})])
        ctx = {"messages": [{"role": "system", "content": "x"}, {"role": "user", "content": "Any smuggler around?"}]}
        self.assertIn("Halted Stream Camp", H.extra_user_text(ctx))
        self.assertEqual(H.extra_user_text(ctx), "")  # told once per talk
        old = H.mode
        H.mode = lambda: 'off'
        try:
            H.reset()
            self.assertEqual(H.extra_user_text(ctx), "")
            self.assertNotIn("knows", H.system_parts({"background": "Bio."}, {}))
        finally:
            H.mode = old

    def test_broken_pack_never_breaks_a_reply(self):
        with open(os.path.join(WK.PACKS_DIR, "broken.json"), "w", encoding="utf-8") as f:
            f.write("{not json")
        conversation(H.CHANNEL_DIR, [("Modded Miller", "FE0801", {"location": "Riverwood"})])
        self.assertIn("mill", H.system_parts({"background": "Bio."}, {}).get("knows", ""))


    def fake_exe(self, ids):
        """A stand-in for Direct AI Connect's src.extensions with registry().speaking_ids = ids (None: no attribute)."""
        import types
        reg = types.SimpleNamespace() if ids is None else types.SimpleNamespace(speaking_ids=ids)
        ext = types.ModuleType("src.extensions")
        ext.registry = lambda: reg
        src = types.ModuleType("src")
        src.extensions = ext
        old = {k: sys.modules.get(k) for k in ("src", "src.extensions")}
        sys.modules.update({"src": src, "src.extensions": ext})

        def undo():
            for k, v in old.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
        self.addCleanup(undo)

    def test_greeting_uses_exe_speakers_before_the_game_writes_them(self):
        conversation(H.CHANNEL_DIR, [("Modded Miller", "FE0801", {"location": "Riverwood"})])
        write(os.path.join(H.CHANNEL_DIR, "conversation.json"), {"string": {"player": "Player"}, "stringList": {"speakers": []}})
        self.assertNotIn("knows", H.system_parts({"background": "Bio."}, {}))  # no exe ids: nothing known yet
        self.fake_exe(["FE0801"])
        self.assertIn("mill's saw broke", H.system_parts({"background": "Bio."}, {}).get("knows", ""))

    def test_stale_speaker_file_replaced_by_exe_speakers(self):
        conversation(H.CHANNEL_DIR, [("Old Talker", "FE0802", {"location": "Whiterun"})])
        write(os.path.join(H.CHANNEL_DIR, "npc", "FE0801.json"), {"string": {"name": "Modded Miller", "location": "Riverwood"}})
        self.fake_exe(["FE0801"])
        self.assertEqual([s['name'] for s in H.world_speakers()], ["Modded Miller"])

    def test_speaker_file_kept_when_it_has_the_exe_speakers(self):
        conversation(H.CHANNEL_DIR, [("Modded Miller", "FE0801", {}), ("Hulda", "013BA3", {})])
        self.fake_exe(["fe0801"])
        self.assertEqual(H.speaker_ids(), ["FE0801", "013BA3"])

    def test_exe_without_speaking_ids_tolerated(self):
        conversation(H.CHANNEL_DIR, [("Modded Miller", "FE0801", {})])
        self.fake_exe(None)
        self.assertEqual(H.speaker_ids(), ["FE0801"])
        self.fake_exe("FE0801")  # not a list
        self.assertEqual(H.exe_speaker_ids(), [])

    def test_register_writes_the_game_checks(self):
        os.makedirs(H.CHANNEL_DIR)

        class Api:
            def on(self, hook, fn):
                pass
        lw_knowledge.register(Api())
        with open(os.path.join(H.CHANNEL_DIR, WK.CHECKS_FILE), encoding="utf-8") as f:
            self.assertEqual(json.load(f)['stringList']['faction_keys'], ["skyrim.esm|039f26"])

    def test_register_survives_a_broken_pack_folder(self):
        WK.PACKS_DIR = os.path.join(self.tmp.name, "missing", "packs")

        class Api:
            def on(self, hook, fn):
                pass
        lw_knowledge.register(Api())  # no packs, no game folder: nothing to write, no error
        self.assertFalse(os.path.exists(os.path.join(H.CHANNEL_DIR, WK.CHECKS_FILE)))


class FakeComponent:
    def __init__(self, kind, *args, **kwargs):
        self.kind, self.args, self.kwargs = kind, args, kwargs

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def click(self, fn, inputs=None, outputs=None, js=None, show_api=True):
        self.kwargs.setdefault('handlers', []).append((fn, inputs, outputs))

    change = click


class FakeGradio:
    def __init__(self):
        self.made = []

    def update(self, **kwargs):
        return kwargs

    def Info(self, text):
        pass

    def __getattr__(self, kind):
        def make(*args, **kwargs):
            component = FakeComponent(kind, *args, **kwargs)
            self.made.append(component)
            return component
        return make


class Page(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.packs = os.path.join(self.tmp.name, "packs")
        self.state = os.path.join(self.tmp.name, "state.json")
        write(os.path.join(self.packs, "mod.json"), {"source": "Some Mod", "entries": [{"id": "a", "text": "T", "conditions": "hold: Rift"}]})

    def tearDown(self):
        self.tmp.cleanup()

    def build(self):
        gr = FakeGradio()
        UI.build(gr, self.packs, self.state, os.path.join(self.tmp.name, "out"))
        return gr

    def button(self, gr, label):
        return next(c for c in gr.made if c.kind == 'Button' and c.args and c.args[0] == label).kwargs['handlers'][0]

    def test_page_builds_and_has_help(self):
        gr = self.build()
        kinds = {c.kind for c in gr.made}
        self.assertTrue({'Dataframe', 'Dropdown', 'Textbox', 'Radio', 'Button', 'File'} <= kinds)
        html = ' '.join(c.args[0] for c in gr.made if c.kind == 'HTML' and c.args and isinstance(c.args[0], str))
        self.assertIn('tooltip-icon', html)
        table = next(c for c in gr.made if c.kind == 'Dataframe')
        self.assertEqual(table.kwargs['value']()[0][:5], ['mod', 'mod', 'Some Mod', 1, 'Yes'])

    def test_page_actions(self):
        gr = self.build()
        make, _, _ = self.button(gr, 'Make pack')
        out = make("My news")
        self.assertEqual(out[1]['value'], "my_news")
        save, _, _ = self.button(gr, 'Save fact')
        out = save("my_news", "", "Bandits took the bridge.", "always", "", "hold: Falkreath", True)
        self.assertIn("Saved", out[-1])
        self.assertEqual(out[2][0][3], "Bandits took the bridge.")
        out = save("my_news", "", "Broken", "always", "", "hold Falkreath", True)
        self.assertIn("Not saved", out[-1])
        self.assertEqual(out[4], "Broken")  # what was typed stays in the editor
        flip, _, _ = self.button(gr, 'Turn pack on/off')
        self.assertEqual(flip("mod")[0][0][4], 'No')
        delete, _, _ = self.button(gr, 'Delete pack')
        self.assertIn("not deleted here", delete(True, "mod")[-1])
        export, _, _ = self.button(gr, 'Export pack')
        file_update, message = export("mod")
        self.assertTrue(os.path.isfile(file_update['value']))
        imp, _, _ = self.button(gr, 'Import')
        out = imp(file_update['value'])
        self.assertIn("Imported", out[-1])


    def test_page_changes_write_the_game_checks(self):
        channel = os.path.join(self.tmp.name, "channel")
        os.makedirs(channel)
        old = H.CHANNEL_DIR
        H.CHANNEL_DIR = channel
        try:
            def checks():
                with open(os.path.join(channel, WK.CHECKS_FILE), encoding="utf-8") as f:
                    return json.load(f)['stringList']
            gr = self.build()
            self.button(gr, 'Make pack')[0]("My news")
            save = self.button(gr, 'Save fact')[0]
            save("my_news", "", "The Jarl is ill.", "always", "", "quest: MQ104 >= 90", True)
            self.assertEqual(checks()['quests'], ["MQ104"])
            self.button(gr, 'Turn pack on/off')[0]("my_news")
            self.assertEqual(checks()['quests'], [])
            self.button(gr, 'Turn pack on/off')[0]("my_news")
            self.assertEqual(checks()['quests'], ["MQ104"])
            entry = WK.find_pack(WK.load_packs(self.packs), "my_news")['entries'][0]['id']
            self.button(gr, 'Turn fact on/off')[0]("my_news", entry)
            self.assertEqual(checks()['quests'], [])
            write(os.path.join(self.tmp.name, "in", "guild.json"), {"name": "Guild news", "entries": [
                {"id": "g", "text": "The guild is back.", "conditions": "global: Skyrim.esm|0x000039 >= 1"}]})
            self.button(gr, 'Import')[0](os.path.join(self.tmp.name, "in", "guild.json"))
            self.assertEqual(checks()['global_keys'], ["skyrim.esm|000039"])
        finally:
            H.CHANNEL_DIR = old


if __name__ == "__main__":
    unittest.main()
