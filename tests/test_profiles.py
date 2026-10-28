import csv
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import build_profiles as BP  # noqa: E402
from lw_knowledge import knowledge as K  # noqa: E402

PROFILES = os.path.join(ROOT, "data", "profiles.json")
CSV = os.environ.get("MANTELLA_CHARACTERS_CSV", BP.DEFAULT_CSV)

ENUMS = {
    "travel": {"home", "regional", "province"},
    "era": {"current", "ancient"},
    "standing": {"low", "common", "high", "ruler"},
    "origin_province": set(BP.PROVINCES),
}


def load_raw():
    pairs_seen = []

    def hook(pairs):
        pairs_seen.append([k for k, _ in pairs])
        return dict(pairs)

    with open(PROFILES, encoding="utf-8") as f:
        data = json.load(f, object_pairs_hook=hook)
    return data, pairs_seen


class Profiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.pairs = load_raw()
        cls.profiles = cls.data["profiles"]

    @unittest.skipUnless(os.path.exists(CSV), "Mantella character CSV not found")
    def test_every_vanilla_row_has_profile(self):
        rows = BP.load_csv(CSV)
        self.assertGreater(len(rows), 3000)
        missing = [r["name"] for r in rows
                   if BP.row_key(r["name"], r["race"], r["base_id"]) not in self.profiles]
        self.assertEqual(missing, [])
        for r in rows[:: 97]:
            p = K.profile_for(r["name"], r["race"], r["base_id"])
            self.assertIsNotNone(p, r["name"])
            self.assertEqual(p["name"], r["name"].strip())

    def test_match_keys_unique(self):
        for keys in self.pairs:
            self.assertEqual(len(keys), len(set(keys)))
        seen = set()
        for key, p in self.profiles.items():
            self.assertEqual(key, K.profile_key(p["name"], p["race"], p["base_id"]))
            self.assertNotIn(key.lower(), seen)
            seen.add(key.lower())

    def test_values_in_range(self):
        professions = set(K.PROFESSIONS) | {"commoner", "child", "beggar", "laborer", "servant",
                                            "noble", "creature", "scholar"}
        for key, p in self.profiles.items():
            with self.subTest(key=key):
                for field, allowed in ENUMS.items():
                    self.assertIn(p[field], allowed)
                self.assertIn(p["observation"], range(1, 5))
                self.assertIn(p["education"], range(1, 6))
                self.assertIn(K.norm_profession(p["profession"]), professions)
                self.assertTrue(p["hold"] is None or p["hold"] in K.HOLDS)
                self.assertTrue(p["home"] is None or isinstance(p["home"], str))
                self.assertIsInstance(p["rated"], bool)
                for t in p["ties"]:
                    self.assertTrue(any(isinstance(t.get(k), str) for k in ("place", "topic",
                                                                             "npc")))
                    self.assertIn(t["level"], range(1, 6))
                    self.assertIsInstance(t["inside"], bool)
                    if t["level"] == 5 and "place" in t:
                        self.assertTrue(t["inside"])

    def test_profile_for_matching(self):
        cam = K.profile_for("Camilla Valerius", "Imperial", "0001347B")
        self.assertEqual(cam["home"], "Riverwood")
        self.assertEqual(K.profile_for("Camilla Valerius")["hold"], "Whiterun Hold")
        self.assertIsNone(K.profile_for("Nobody At All", "Nord", "FFFFFF"))

    def test_plan_cases_from_shipped_profiles(self):
        cam = K.profile_for("Camilla Valerius", "Imperial", "01347B")
        self.assertEqual(K.place_level(cam, {"name": "Bleak Falls Barrow",
                                             "hold": "Falkreath Hold", "kind": "dungeon"}), 4)
        far = K.profile_for("Farengar Secret-Fire", "Nord", "013BBB")
        self.assertEqual(K.topic_level(far, "dragonstone"), 5)
        ser = K.profile_for("Serana", "Nord", "002B6C")
        self.assertEqual(ser["era"], "ancient")
        self.assertEqual(K.topic_level(ser, "civil_war"), 1)

    def test_rated_share(self):
        rated = sum(1 for p in self.profiles.values() if p["rated"])
        self.assertGreater(rated, 0)


if __name__ == "__main__":
    unittest.main()
