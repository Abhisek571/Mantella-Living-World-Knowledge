import json
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "server"))

import build_knows as B  # noqa: E402
from lw_knowledge import knows as N  # noqa: E402

LUCAN = {"name": "Lucan Valerius", "base_id": "01347A",
         "always": ["You and your sister Camilla run the Riverwood Trader.",
                    "You never tell anyone where you got the golden claw, not even Camilla."],
         "when": [{"quest": "MS13", "state": "not_done", "lines": ["There was a break-in; the robbers took only the golden claw."]},
                  {"quest": "MS13", "state": "done", "lines": ["The claw is back where it belongs."]}],
         "secret": ""}
DELPHINE = {"name": "Delphine", "base_id": "013478", "always": ["You run the Sleeping Giant Inn with Orgnar."], "when": [],
            "secret": "You are one of the last Blades; you never reveal it to strangers."}
BAD = {"name": "Bad Npc", "base_id": "000001",
       "always": ["You know the quest reward is 500 gold.", "x " * 40],
       "when": [{"quest": "NOPE", "state": "running", "lines": ["Unknown quest."]},
                {"quest": "MS13", "state": "sometimes", "lines": ["Bad state."]}], "secret": ""}


class Knows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = os.path.join(cls.tmp.name, "lore.sqlite")
        sqlite3.connect(cls.db).close()
        cls.report = B.load_blocks([LUCAN, DELPHINE, BAD], cls.db, {"MS13", "MQ103"})
        cls.quests_file = os.path.join(cls.tmp.name, "knowledge_quests.json")
        B.write_quest_list(cls.db, cls.quests_file)

    @classmethod
    def tearDownClass(cls):
        N.reset()
        cls.tmp.cleanup()

    def lines(self, name, base_id, states):
        return N.knows_lines(name, base_id, states, db_path=self.db)

    def test_state_picks_lines(self):
        running = self.lines("Lucan Valerius", "01347A", {"MS13": 1})
        self.assertIn("There was a break-in; the robbers took only the golden claw.", running)
        self.assertNotIn("The claw is back where it belongs.", running)
        done = self.lines("Lucan Valerius", "01347A", {"MS13": 2})
        self.assertIn("The claw is back where it belongs.", done)
        self.assertNotIn("There was a break-in; the robbers took only the golden claw.", done)

    def test_no_quest_data_means_always_lines_only(self):
        self.assertEqual(self.lines("Lucan Valerius", "01347A", None),
                         ["You and your sister Camilla run the Riverwood Trader.",
                          "You never tell anyone where you got the golden claw, not even Camilla."])

    def test_secret_kept_and_marked(self):
        text = N.knows_block("Delphine", "013478", {}, db_path=self.db)
        self.assertIn("Sleeping Giant", text)
        self.assertIn("never reveal it to strangers", text)
        self.assertTrue(text.startswith("What Delphine knows"))

    def test_bad_rows_rejected(self):
        self.assertEqual(self.lines("Bad Npc", "000001", {"MS13": 1}), [])
        self.assertGreaterEqual(self.report["rejected"], 4, self.report)

    def test_lute_player_is_not_meta(self):
        self.assertTrue(B.good_line("You are a lute player at the inn."))
        self.assertFalse(B.good_line("The player saved the College."))

    def test_match_by_name_when_base_id_differs(self):
        self.assertTrue(self.lines("Lucan Valerius", "FFFFFF", {"MS13": 1}))

    def test_unknown_npc_empty(self):
        self.assertEqual(N.knows_block("Nobody", "000002", {}, db_path=self.db), "")

    def test_quest_list_for_world(self):
        data = json.load(open(self.quests_file, encoding="utf-8"))
        self.assertEqual(data, {"stringList": {"quests": ["MQ101", "MQ102", "MQ104", "MQ105", "MS13"]}})

    def test_later_block_replaces_earlier_one(self):
        # long_*.json redoes NPCs whose wiki text was cut in their batch; the later file wins
        old = dict(LUCAN, always=["Old cut-off line."], when=[])
        merged = B.merge_blocks([[old, DELPHINE], [LUCAN]])
        self.assertEqual([b["name"] for b in merged], ["Lucan Valerius", "Delphine"])
        self.assertEqual(merged[0]["always"], LUCAN["always"])

    def test_missing_db_is_empty(self):
        self.assertEqual(N.knows_block("Lucan Valerius", "01347A", {}, db_path=os.path.join(self.tmp.name, "nope.sqlite")), "")


if __name__ == "__main__":
    unittest.main()
