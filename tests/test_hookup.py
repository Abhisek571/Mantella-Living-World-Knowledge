"""The Knowledge extension's hooks into Mantella: system parts (common knowledge, identity, never-inside lines) and
per-reply lore lines, for the speakers in the game's conversation file."""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

import lw_knowledge  # noqa: E402
from lw_knowledge import hookup as H  # noqa: E402


class FakeApi:
    def __init__(self):
        self.hooks = {}

    def on(self, hook, fn):
        self.hooks.setdefault(hook, []).append(fn)


def conversation(tmp, speakers):
    os.makedirs(os.path.join(tmp, "npc"), exist_ok=True)
    for name, base in speakers:
        with open(os.path.join(tmp, "npc", base + ".json"), "w", encoding="utf-8") as f:
            json.dump({"string": {"name": name, "ref_id": "00" + base}, "int": {}}, f)
    with open(os.path.join(tmp, "conversation.json"), "w", encoding="utf-8") as f:
        json.dump({"string": {"player": "Player"}, "stringList": {"speakers": [b for _, b in speakers]}}, f)


def user(text):
    return {"messages": [{"role": "system", "content": "x"}, {"role": "user", "content": text}]}


class Hookup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        H.CHANNEL_DIR = self.tmp.name
        H.reset()

    def tearDown(self):
        self.tmp.cleanup()

    def test_register_adds_both_hooks(self):
        api = FakeApi()
        lw_knowledge.register(api)
        self.assertEqual(sorted(api.hooks), ["extra_user_text", "system_parts"])

    def test_system_parts_add_common_knowledge_and_identity(self):
        conversation(self.tmp.name, [("Camilla Valerius", "01347B")])
        hub = {"prompt_rules": "r", "background": "Camilla is an Imperial.", "__order__": ["prompt_rules", "background"],
               "__breakpoints_after__": [["background", "identity", "knows"], "respond"]}
        parts = H.system_parts(dict(hub), {})
        self.assertIn("common_knowledge", parts)
        self.assertIn("identity", parts)
        # the Hub owns the order and the cache points; Knowledge only adds its parts
        self.assertEqual(parts["__order__"], hub["__order__"])
        self.assertEqual(parts["__breakpoints_after__"], hub["__breakpoints_after__"])
        self.assertNotIn("__breakpoint_after__", parts)
        self.assertIn("Camilla Valerius", parts["identity"])
        self.assertIn("never been inside Bleak Falls Barrow", parts["identity"])

    def test_knows_part_uses_quest_state_from_world(self):
        conversation(self.tmp.name, [("Camilla Valerius", "01347B")])
        with open(os.path.join(self.tmp.name, "world.json"), "w", encoding="utf-8") as f:
            json.dump({"quest_state": {"MS13": 1}, "quests": {"MS13": 10}}, f)
        seen = {}
        def fake_block(name, base_id, states, db_path=None):
            seen.update(name=name, base_id=base_id, states=states)
            return f"What {name} knows:\n- Thieves took the claw."
        old = H.N.knows_block
        H.N.knows_block = fake_block
        try:
            parts = H.system_parts({"background": "Bio."}, {})
        finally:
            H.N.knows_block = old
        self.assertIn("Thieves took the claw", parts.get("knows", ""))
        self.assertEqual(seen["states"], {"MS13": 1})
        self.assertEqual(seen["base_id"], "01347B")

    def test_bio_quest_stage_lines_dropped_when_block_exists(self):
        bio = ("# Background\nCamilla is an Imperial.\nWhen flirting: “You’re a strapping young man!”\n"
               "If the golden claw has been returned: \"It means so much to us!\"\n"
               "After you finish The Golden Claw: \"Thanks.\"\nRegarding the bandits: \"Mad, hiding out there.\"")
        self.assertEqual(H.strip_stage_lines(bio),
                         "# Background\nCamilla is an Imperial.\nWhen flirting: “You’re a strapping young man!”\n"
                         "Regarding the bandits: \"Mad, hiding out there.\"")

    def test_ore_job_names_a_mine(self):
        conversation(self.tmp.name, [("Alvor", "013482")])
        path = os.path.join(self.tmp.name, "npc", "013482.json")
        data = json.load(open(path, encoding="utf-8"))
        data["string"]["job"] = "You need Iron Ore brought to you; you posted a notice on the job board for it."
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        parts = H.system_parts({"background": "Bio."}, {})
        self.assertIn("Iron Ore", parts["identity"])
        self.assertIn("knows where Iron Ore is mined", parts["identity"])

    def test_character_if_lines_kept(self):
        bio = "If asked about her past: \"I'd rather not.\"\nIf the golden claw has been returned: \"Thanks.\""
        self.assertEqual(H.strip_stage_lines(bio), "If asked about her past: \"I'd rather not.\"")

    def test_job_goes_to_its_own_speaker(self):
        # a mod NPC without a profile first in the group must not shift Alvor's job onto someone else
        conversation(self.tmp.name, [("Modded Stranger", "FE0811"), ("Alvor", "013482")])
        path = os.path.join(self.tmp.name, "npc", "013482.json")
        data = json.load(open(path, encoding="utf-8"))
        data["string"]["job"] = "You need Iron Ore brought to you."
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        hints = H.gather_hints(H.speaker_profiles())
        self.assertTrue(all(h.startswith("Alvor ") for h in hints) and hints, hints)

    def test_lore_sent_again_in_a_new_talk(self):
        conversation(self.tmp.name, [("Camilla Valerius", "01347B")])
        first = H.extra_user_text(user("What do you know about Bleak Falls Barrow?"))
        H.extra_user_text({"messages": [{"role": "system", "content": "x"}, {"role": "user", "content": "Hello."},
                                        {"role": "assistant", "content": "Hi."}, {"role": "user", "content": "Bye."}]})
        again = H.extra_user_text(user("What do you know about Bleak Falls Barrow?"))  # a new talk: fewer messages
        self.assertEqual(first, again)

    def test_non_utf8_npc_file_read(self):
        conversation(self.tmp.name, [("Camilla Valerius", "01347B")])
        with open(os.path.join(self.tmp.name, "npc", "01347B.json"), "wb") as f:
            f.write('{"string": {"name": "Camilla Valerius", "note": "café"}}'.encode("cp1252"))
        self.assertTrue(H.speaker_profiles())

    def test_knowledge_mode_off_and_profiles_only(self):
        conversation(self.tmp.name, [("Camilla Valerius", "01347B")])
        settings = os.path.join(self.tmp.name, "settings.json")
        old = H.HUB_SETTINGS
        H.HUB_SETTINGS = settings
        try:
            with open(settings, "w", encoding="utf-8") as f:
                json.dump({"knowledge_mode": "off"}, f)
            self.assertEqual(H.system_parts({"background": "Bio."}, {}), {"background": "Bio."})
            self.assertEqual(H.extra_user_text(user("Tell me about Bleak Falls Barrow.")), "")
            with open(settings, "w", encoding="utf-8") as f:
                json.dump({"knowledge_mode": "profiles"}, f)
            self.assertIn("identity", H.system_parts({"background": "Bio."}, {}))
            self.assertEqual(H.extra_user_text(user("Tell me about Bleak Falls Barrow.")), "")
        finally:
            H.HUB_SETTINGS = old

    def test_no_world_means_no_quest_states(self):
        conversation(self.tmp.name, [("Camilla Valerius", "01347B")])
        self.assertIsNone(H.quest_states())

    def test_identity_line_under_40_tokens(self):
        conversation(self.tmp.name, [("Camilla Valerius", "01347B")])
        first = H.identity_lines([H.speaker_profiles()[0]]).splitlines()[0]
        self.assertLessEqual((len(first) + 3) // 4, 40, first)

    def test_never_inside_only_for_tied_places(self):
        conversation(self.tmp.name, [("Camilla Valerius", "01347B")])
        text = H.identity_lines(H.speaker_profiles())
        made = H.identity_text(H.speaker_profiles()[0])
        self.assertEqual(H.identity_lines([dict(H.speaker_profiles()[0], lines=made)]), H.identity_lines([H.speaker_profiles()[0]]))
        self.assertEqual(H.identity_lines([{'name': 'X', 'lines': 'Identity: X is ready-made.'}]), 'Identity: X is ready-made.')
        self.assertNotIn("never been inside Riverwood Trader", text)

    def test_bio_fixes_for_speakers_only(self):
        wrong = 'Aventus Avenicci: Her father.'
        H._bio_fixes['list'] = [{'name': 'Adrianne Avenicci', 'find': wrong, 'replace': 'Proventus Avenicci: Her father.'},
                                {'name': 'Lydia', 'find': 'the player absorbed its soul.', 'replace': ''}]
        try:
            self.assertEqual(H.fix_bios(wrong, {'Adrianne Avenicci'}), 'Proventus Avenicci: Her father.')
            self.assertEqual(H.fix_bios(wrong, {'Lydia'}), wrong)
            self.assertEqual(H.fix_bios('Then the player absorbed its soul.', {'Lydia'}), 'Then ')
        finally:
            H._bio_fixes['list'] = None

    def test_shipped_bio_fixes_load(self):
        H._bio_fixes['list'] = None
        H.fix_bios('', set())
        self.assertGreaterEqual(len(H._bio_fixes['list']), 10)

    def test_no_speakers_changes_nothing(self):
        parts = {"mantella": "You are someone.", "__breakpoint_after__": "mantella"}
        self.assertEqual(H.system_parts(dict(parts), {}), parts)
        self.assertEqual(H.extra_user_text(user("Tell me about Bleak Falls Barrow.")), "")

    def test_lore_line_for_a_named_place(self):
        conversation(self.tmp.name, [("Camilla Valerius", "01347B")])
        text = H.extra_user_text(user("What do you know about Bleak Falls Barrow?"))
        self.assertTrue(text.startswith("(What Camilla Valerius knows about this:"), text)
        self.assertLessEqual((len(text) + 3) // 4, H.lore_budget() + 30)

    def test_no_trigger_no_lore(self):
        conversation(self.tmp.name, [("Camilla Valerius", "01347B")])
        self.assertEqual(H.extra_user_text(user("Nice weather today.")), "")

    def test_same_fact_not_repeated_in_one_talk(self):
        conversation(self.tmp.name, [("Camilla Valerius", "01347B")])
        first = H.extra_user_text(user("What do you know about Bleak Falls Barrow?"))
        second = H.extra_user_text(user("And Bleak Falls Barrow again?"))
        self.assertTrue(first)
        self.assertNotEqual(first, second)

    def test_events_in_parentheses_ignored(self):
        conversation(self.tmp.name, [("Camilla Valerius", "01347B")])
        self.assertEqual(H.extra_user_text(user("(Player walked past Bleak Falls Barrow.) Hello.")), "")


if __name__ == "__main__":
    unittest.main()
