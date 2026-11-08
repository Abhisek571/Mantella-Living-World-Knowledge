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
        self.assertEqual(data, {"stringList": {"quests": sorted(set(B.ALWAYS_TRACKED) | {"MS13"})}})
        # the Dragonborn line and the end of the war need their quests tracked too
        from lw_knowledge import dragonborn as D
        self.assertLessEqual(set(D.QUESTS) | {"CWFinale"}, set(data["stringList"]["quests"]))

    def test_later_block_replaces_earlier_one(self):
        # long_*.json redoes NPCs whose wiki text was cut in their batch; the later file wins
        old = dict(LUCAN, always=["Old cut-off line."], when=[])
        merged = B.merge_blocks([[old, DELPHINE], [LUCAN]])
        self.assertEqual([b["name"] for b in merged], ["Lucan Valerius", "Delphine"])
        self.assertEqual(merged[0]["always"], LUCAN["always"])

    def test_secret_tied_to_quest_stage(self):
        maro = {"name": "Commander Maro", "base_id": "01D4B5", "always": ["Your son Gaius serves the Emperor."], "when": [],
                "secret": "You plan to slaughter the Brotherhood for killing your son."}
        blocks = [maro, dict(DELPHINE)]
        fixes = {"secret": [{"name": "Commander Maro", "quest": "DB06", "state": "done"}]}
        self.assertEqual(B.apply_fixes(blocks, fixes), 1)
        db = os.path.join(self.tmp.name, "secret_stage.sqlite")
        B.load_blocks(blocks, db, {"DB06"})
        for states in (None, {}, {"DB06": 0}, {"DB06": 1}):
            text = N.knows_block("Commander Maro", "01D4B5", states, db_path=db)
            self.assertNotIn("slaughter", text, states)
            self.assertIn("Gaius", text)
        self.assertIn("- Secret: You plan to slaughter", N.knows_block("Commander Maro", "01D4B5", {"DB06": 2}, db_path=db))
        self.assertNotIn("slaughter", " ".join(N.knows_lines("Commander Maro", "01D4B5", {"DB06": 2}, db_path=db)))
        # an untied secret is still always there
        self.assertIn("last Blades", N.knows_block("Delphine", "013478", None, db_path=db))
        # a stage on an unknown quest is rejected, not shown untied
        rows, rejected = B.rows_for(dict(maro, secret_quest="NOPE", secret_state="done"), {"DB06"})
        self.assertEqual((len(rows), rejected), (1, 1))

    def test_side_and_path_condition(self):
        # FAC-2/FAC-3: a shared quest's ending is told only to the side that fought it
        isran = {"name": "Isran", "base_id": "00336A", "always": ["You lead the Dawnguard."],
                 "when": [{"quest": "DLC1VQ08", "state": "done", "lines": ["Harkon is dead and the Dawnguard keeps the bow."]}]}
        vignar = {"name": "Vignar Gray-Mane", "base_id": "013BB5", "always": ["You are an old warrior of Whiterun."],
                  "when": [{"quest": "CWSiegeObj", "state": "done", "lines": ["The people named you Jarl."]}]}
        fixes = {"also": [{"name": "Isran", "quest": "DLC1VQ08", "state": "done", "also_quest": "DLC1VQ03Hunter",
                           "also_state": "started"},
                          {"name": "Vignar Gray-Mane", "quest": "CWSiegeObj", "state": "done", "also_quest": "war_side",
                           "also_state": "Stormcloaks"}]}
        blocks = [isran, vignar]
        self.assertEqual(B.apply_fixes(blocks, fixes), 2)
        db = os.path.join(self.tmp.name, "also.sqlite")
        B.load_blocks(blocks, db, {"DLC1VQ08", "DLC1VQ03Hunter", "CWSiegeObj"})
        vampire = {"DLC1VQ08": 2, "DLC1VQ03Hunter": 0}
        self.assertNotIn("keeps the bow", " ".join(N.knows_lines("Isran", "00336A", vampire, db_path=db)))
        self.assertIn("keeps the bow", " ".join(N.knows_lines("Isran", "00336A", {"DLC1VQ08": 2, "DLC1VQ03Hunter": 2}, db_path=db)))
        self.assertNotIn("named you Jarl", " ".join(N.knows_lines("Vignar Gray-Mane", "013BB5", {"CWSiegeObj": 2}, db_path=db)))
        self.assertNotIn("named you Jarl", " ".join(N.knows_lines("Vignar Gray-Mane", "013BB5",
                                                                  {"CWSiegeObj": 2, "war_side": "Legion"}, db_path=db)))
        self.assertIn("named you Jarl", " ".join(N.knows_lines("Vignar Gray-Mane", "013BB5",
                                                               {"CWSiegeObj": 2, "war_side": "Stormcloaks"}, db_path=db)))
        # the second quest is tracked for World; war_side is not a quest
        out = os.path.join(self.tmp.name, "also_quests.json")
        quests = B.write_quest_list(db, out)
        self.assertIn("DLC1VQ03Hunter", quests)
        self.assertNotIn("war_side", quests)
        # a bad side or an unknown second quest is rejected
        bad = dict(vignar, when=[dict(vignar["when"][0], also_quest="war_side", also_state="Thalmor")])
        self.assertEqual(B.rows_for(bad, {"CWSiegeObj"})[1], 1)

    def test_tied_line_and_pointer_quest(self):
        # SCH-9: an untied line tied to quest stages; SCH-7: a pointer quest's rows go to the real quest
        serana = {"name": "Serana", "base_id": "002B6C",
                  "always": ["You are Serana, a vampire.", "You slept a long time and never heard of Ulfric.",
                             "Your father wants a prophecy fulfilled."], "when": [],
                  "secret": "You keep your past to yourself."}
        orthus = {"name": "Orthus Endario", "base_id": "0DEADB", "always": [],
                  "when": [{"quest": "MS10MiscObjPointer", "state": "done", "lines": ["The pirate haven is destroyed."]}]}
        fixes = {"tie": [{"name": "Serana", "starts": "You slept", "states": [["DLC1VQ02", "not_done"]]},
                         {"name": "Serana", "starts": "Your father", "states": [["DLC1VQ04", "secret:not_done"],
                                                                                ["DLC1VQ04", "done"]]}]}
        blocks = [serana, orthus]
        self.assertEqual(B.apply_fixes(blocks, fixes), 2)
        db = os.path.join(self.tmp.name, "tie.sqlite")
        B.load_blocks(blocks, db, {"DLC1VQ02", "DLC1VQ04", "MS10MiscObjPointer"})
        early = {"DLC1VQ02": 1, "DLC1VQ04": 0}
        self.assertIn("never heard of Ulfric", " ".join(N.knows_lines("Serana", "002B6C", early, db_path=db)))
        self.assertNotIn("never heard of Ulfric", " ".join(N.knows_lines("Serana", "002B6C", {"DLC1VQ02": 2}, db_path=db)))
        block = N.knows_block("Serana", "002B6C", early, db_path=db)
        self.assertNotIn("prophecy", " ".join(N.knows_lines("Serana", "002B6C", early, db_path=db)))
        self.assertIn("- Secret: You keep your past to yourself. Your father wants a prophecy", block)
        self.assertIn("prophecy", " ".join(N.knows_lines("Serana", "002B6C", {"DLC1VQ02": 2, "DLC1VQ04": 2}, db_path=db)))
        self.assertIn("pirate haven", " ".join(N.knows_lines("Orthus Endario", "0DEADB", {"MS10": 2}, db_path=db)))
        self.assertEqual(N.knows_lines("Orthus Endario", "0DEADB", {"MS10MiscObjPointer": 2, "MS10": 1}, db_path=db), [])
        self.assertIn("MS10", B.write_quest_list(db, os.path.join(self.tmp.name, "tie_quests.json")))

    def test_secret_marked_in_group_talk(self):
        # FAC-6: one model writes every line of a group talk
        alone = N.knows_block("Delphine", "013478", None, db_path=self.db)
        group = N.knows_block("Delphine", "013478", None, db_path=self.db, speakers=2)
        self.assertIn("- Secret: You are one of the last Blades", alone)
        self.assertIn("- Secret only Delphine knows; never said in front of the others here: You are one", group)

    def test_old_db_without_second_condition_still_reads(self):
        db = os.path.join(self.tmp.name, "old.sqlite")
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE npc_knows (npc TEXT NOT NULL, base_id TEXT, quest TEXT, state TEXT, seq INTEGER, "
                    "text TEXT NOT NULL, tokens INTEGER)")
        con.execute("INSERT INTO npc_knows VALUES ('delphine', '013478', '', '', 0, 'You run the inn.', 4)")
        con.commit()
        con.close()
        self.assertEqual(N.knows_lines("Delphine", "013478", None, db_path=db), ["You run the inn."])

    def test_shipped_side_conditions(self):
        db = os.path.join(ROOT, "data", "lore.sqlite")
        if not os.path.exists(db):
            self.skipTest("no lore.sqlite")
        legion = {"CWSiegeObj": 2, "CWObj": 2, "CWMission04": 2, "war_side": "Legion"}
        self.assertFalse(any("Jarl" in l for l in N.knows_lines("Vignar Gray-Mane", "013BB5", legion, db_path=db)))
        self.assertFalse(any("Steward" in l for l in N.knows_lines("Tekla", "013656", legion, db_path=db)))
        self.assertFalse(any("Solitude has fallen" in l for l in N.knows_lines("Galmar Stone-Fist", "014128", legion, db_path=db)))
        vampire = {"DLC1VQ08": 2, "DLC1VQ03Vampire": 1, "DLC1VQ03Hunter": 0}
        self.assertFalse(any("Auriel's Bow" in l for l in N.knows_lines("Isran", "00336A", vampire, db_path=db)))
        self.assertFalse(any("at Castle Volkihar" in l for l in N.knows_lines("Agmaer", "00336E", vampire, db_path=db)))
        dawnguard = {"DLC1VQ08": 2, "DLC1VQ03Vampire": 0, "DLC1VQ03Hunter": 2}
        self.assertEqual(N.knows_lines("Garan Marethi", "003364", dawnguard, db_path=db)[-1:],
                         N.knows_lines("Garan Marethi", "003364", {}, db_path=db)[-1:])
        self.assertTrue(any("Ulfric" in l for l in N.knows_lines("Serana", "002B6C", {"DLC1VQ02": 0}, db_path=db)))
        self.assertFalse(any("Ulfric" in l for l in N.knows_lines("Serana", "002B6C", {"DLC1VQ02": 2}, db_path=db)))
        N.reset()

    def test_missing_db_is_empty(self):
        self.assertEqual(N.knows_block("Lucan Valerius", "01347A", {}, db_path=os.path.join(self.tmp.name, "nope.sqlite")), "")


if __name__ == "__main__":
    unittest.main()
