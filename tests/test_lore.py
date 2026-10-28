import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "server"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lw_knowledge import lore as L  # noqa: E402
from test_lore_build import build_fixture_db  # noqa: E402

CAMILLA = {"name": "Camilla Valerius", "home": "Riverwood", "hold": "Whiterun Hold",
           "origin_province": "Cyrodiil", "profession": "merchant", "travel": "home",
           "era": "current", "observation": 2, "education": 3,
           "ties": [{"place": "Bleak Falls Barrow", "level": 4, "inside": False}]}
DELVER = dict(CAMILLA, name="Arvel the Swift",
              ties=[{"place": "Bleak Falls Barrow", "level": 5, "inside": True}])
STRANGER = {"name": "Stranger", "home": "Markarth", "hold": "The Reach", "profession": "farmer"}


class Lookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db, _ = build_fixture_db(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        if L._DB is not None:
            L._DB.con.close()
        L._DB = None
        cls.tmp.cleanup()

    def look(self, text, profile, budget=300, **kw):
        return L.lookup(text, profile, budget, db_path=self.db, **kw)

    def test_camilla_gets_no_inside_facts(self):
        lines = self.look("What is inside Bleak Falls Barrow? How do the doors open?", CAMILLA)
        self.assertTrue(lines)
        joined = " ".join(lines)
        for leak in ("pillar", "claw", "lever", "word wall", "darts"):
            self.assertNotIn(leak, joined)
        self.assertIn("dead do not rest", joined)

    def test_nobody_gets_inside_facts_of_dangerous_places(self):
        joined = " ".join(self.look("Tell me about Bleak Falls Barrow pillars", DELVER))
        self.assertTrue(joined)
        for leak in ("pillar", "claw", "lever", "word wall", "darts"):
            self.assertNotIn(leak, joined)

    def test_dangerous_place_is_one_rumor(self):
        lines = self.look("What do you know about Bleak Falls Barrow?", CAMILLA)
        self.assertEqual(len(lines), 1)
        for wiki in ("draugr", "bandit", "skeever", "medium-sized", "Skyrim", "containing"):
            self.assertNotIn(wiki, lines[0])
        self.assertIn("Riverwood", lines[0])

    def test_home_not_looked_up(self):
        self.assertEqual(self.look("You are now in Riverwood.", CAMILLA), [])

    def test_place_secret_only_for_those_in_on_it(self):
        farengar = dict(STRANGER, name="Farengar Secret-Fire", home="Whiterun")
        self.assertIn("Dragonstone", " ".join(self.look("Bleak Falls Barrow", farengar)))
        self.assertNotIn("Dragonstone", " ".join(self.look("Bleak Falls Barrow", CAMILLA)))

    def test_far_stranger_gets_only_lead(self):
        lines = self.look("Bleak Falls Barrow", STRANGER)
        self.assertEqual(len(lines), 1)

    def test_budget_respected(self):
        for budget in (10, 25, 40, 80, 150):
            lines = self.look("Bleak Falls Barrow, Riverwood and Camilla", DELVER, budget)
            self.assertLessEqual(sum((len(x) + 3) // 4 for x in lines), budget)
        self.assertEqual(self.look("Riverwood", CAMILLA, 0), [])

    def test_no_trigger_no_lookup(self):
        db = L.get_db(self.db)
        before = db.queries
        self.assertEqual(self.look("Nice weather today, friend. Got any work?", CAMILLA), [])
        self.assertEqual(self.look("", CAMILLA), [])
        self.assertEqual(db.queries, before)
        self.look("Have you been to Riverwood?", STRANGER)
        self.assertEqual(db.queries, before + 1)

    def test_redirect_and_first_name_trigger(self):
        self.assertTrue(self.look("what about bleak falls", CAMILLA))
        self.assertTrue(self.look("do you know camilla", dict(STRANGER, home="Riverwood",
                                                               hold="Whiterun Hold")))

    def test_people_one_line_only_for_their_town(self):
        local = dict(STRANGER, name="Hod", home="Riverwood", hold="Whiterun Hold")
        lines = self.look("Do you know Camilla Valerius?", local)
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith("Camilla Valerius is"), lines)
        self.assertIn("Riverwood", lines[0])
        # a far-away commoner has never heard of her
        self.assertEqual(self.look("Do you know Camilla Valerius?", STRANGER), [])

    def test_guide_text_filtered(self):
        for bad in ("You can sell firewood to the mill owner.", "It can be found west of Riverwood.",
                    "The Dragonborn may receive a quest here.", "He wears hide armor and carries an iron sword.",
                    "She starts her day at 6am with breakfast."):
            self.assertTrue(L.is_guide_text(bad), bad)
        self.assertFalse(L.is_guide_text("Riverwood sits on the bank of the White River below the old barrow."))

    def test_secret_gated(self):
        plain = " ".join(self.look("Who is Alduin?", CAMILLA))
        self.assertNotIn("raising", plain)
        esbern = dict(CAMILLA, name="Esbern")
        self.assertIn("raising", " ".join(self.look("Who is Alduin?", esbern)))

    def test_sent_facts_not_repeated(self):
        sent = set()
        first = self.look("Riverwood", STRANGER, sent=sent)
        second = self.look("Riverwood", STRANGER, sent=sent)
        self.assertTrue(first)
        self.assertFalse(set(first) & set(second))

    def test_missing_db_is_empty(self):
        self.assertEqual(L.lookup("Riverwood", CAMILLA, 100, db_path="nope.sqlite"), [])


REAL_DB = os.path.join(ROOT, "data", "lore.sqlite")


@unittest.skipUnless(os.path.exists(REAL_DB), "data/lore.sqlite not built")
class RealDatabase(unittest.TestCase):
    def test_size_and_speed(self):
        import sqlite3
        con = sqlite3.connect(REAL_DB)
        total = con.execute("SELECT sum(tokens) FROM facts").fetchone()[0]
        con.close()
        self.assertLessEqual(total, 1_100_000)
        L.lookup("warm up Whiterun", CAMILLA, 150, db_path=REAL_DB)
        lines_all = []
        t0 = time.perf_counter()
        for text in ("What do you know about Bleak Falls Barrow?",
                     "Tell me about Whiterun and the Companions.",
                     "Have you heard of Farengar Secret-Fire or the Thalmor?",
                     "Nothing to see here, just chatting about the weather."):
            lines_all.append(L.lookup(text, CAMILLA, 150, db_path=REAL_DB))
        per = (time.perf_counter() - t0) / 4
        self.assertLess(per, 0.05)
        joined = " ".join(lines_all[0])
        self.assertTrue(lines_all[0])
        for leak in ("pillar", "claw", "puzzle", "word wall", "Snake"):
            self.assertNotIn(leak, joined)
        self.assertEqual(lines_all[3], [])


if __name__ == "__main__":
    unittest.main()
