import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "server"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import build_lore as B  # noqa: E402
import fixtures as F  # noqa: E402


def build_fixture_db(folder):
    db = os.path.join(folder, "lore.sqlite")
    places = os.path.join(folder, "places.json")
    B.build_db(B.collect(F.PAGES), F.REDIRECTS, db, places)
    return db, places


class LoreBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db, cls.places = build_fixture_db(cls.tmp.name)
        cls.con = sqlite3.connect(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        cls.tmp.cleanup()

    def facts(self, key):
        return self.con.execute(
            "SELECT f.depth, f.inside, f.section, f.text, f.secret FROM facts f "
            "JOIN articles a ON a.id = f.article WHERE a.key = ? ORDER BY f.seq", (key,)).fetchall()

    def test_markup_stripped(self):
        for (text,) in self.con.execute("SELECT text FROM facts"):
            for bad in ("[[", "]]", "{{", "}}", "'''", "<ref", "{|", "|}", "Category:"):
                self.assertNotIn(bad, text)
        plain = B.strip_markup("A [[Skyrim:Nords|Nord]] tomb in {{Skyrim}}.<ref>x</ref> "
                               "'''Bold''' [[Riverwood (Skyrim)]] [[File:A.png|thumb|cap]].")
        self.assertEqual(plain, "A Nord tomb in Skyrim. Bold Riverwood.")

    def test_dropped_sections(self):
        sections = {r[2] for r in self.facts("bleak falls barrow")}
        self.assertNotIn("Bugs", sections)
        self.assertFalse(any("console" in r[3] for r in self.facts("bleak falls barrow")))
        self.assertFalse(any("firewood" in r[3] for r in self.facts("riverwood")))
        self.assertFalse(any("better life" in r[3] for r in self.facts("camilla valerius")))

    def test_bleak_falls_inside_facts_tagged_inside(self):
        rows = self.facts("bleak falls barrow")
        inside = [r for r in rows if r[1]]
        outside = [r for r in rows if not r[1]]
        self.assertTrue(any("pillars" in r[3] for r in inside))
        self.assertTrue(any("golden claw" in r[3] for r in inside))
        self.assertTrue(all(r[0] == 5 for r in inside))
        self.assertFalse(any("pillars" in r[3] or "claw" in r[3] for r in outside))
        self.assertTrue(any(r[0] <= 2 and "Nordic ruin" in r[3] for r in outside))

    def test_fact_size_limit(self):
        for (n,) in self.con.execute("SELECT tokens FROM facts"):
            self.assertLessEqual(n, B.MAX_FACT_TOKENS)

    def test_secret_tagged(self):
        self.assertTrue(any(r[4] == "alduin_raises_dragons" for r in self.facts("alduin")))

    def test_names_and_places(self):
        names = dict(self.con.execute("SELECT name, article FROM names"))
        self.assertIn("bleak falls barrow", names)
        self.assertIn("bleak falls", names)      # redirect
        self.assertIn("camilla", names)          # unique first name
        import json
        with open(self.places, encoding="utf-8") as f:
            places = json.load(f)
        self.assertEqual(places["Bleak Falls Barrow"]["hold"], "Falkreath Hold")
        self.assertEqual(places["Bleak Falls Barrow"]["kind"], "dungeon")
        self.assertEqual(places["Riverwood"]["kind"], "town")

    def test_fts_index(self):
        n = self.con.execute("SELECT count(*) FROM facts_fts WHERE facts_fts MATCH 'pillars'")
        self.assertGreaterEqual(n.fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
