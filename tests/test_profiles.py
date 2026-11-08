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

    def test_neloth_stays_on_solstheim(self):
        # SCH-12: he never leaves Tel Mithryn
        p = self.profiles["Neloth|Dunmer|01773A"]
        self.assertEqual(p["travel"], "regional")
        self.assertNotIn("all over Skyrim", p["lines"])

    def test_orc_chiefs_do_not_rule_the_hold(self):
        for key in ("Chief Burguk|Orsimer|013B79", "Chief Mauhulakh|Orsimer|01B075"):
            self.assertEqual(self.profiles[key]["standing"], "high", key)

    def test_observation_file_for_world(self):
        import tempfile
        profiles = {"a": {"base_id": "01A68E", "observation": 4}, "b": {"base_id": "978AA", "observation": 3},
                    "c": {"base_id": "013BBD", "observation": 2}, "d": {"base_id": "821", "observation": 4},
                    "e": {"base_id": "000D62", "observation": 3}, "f": {"base_id": "000D62", "observation": 2},
                    "g": {"base_id": "", "observation": 3}}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "observation.json")
            self.assertEqual(BP.write_observation(profiles, path), 2)
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"int": {"01a68e": 4, "0978aa": 3}})

    def test_shipped_observation_file_matches_profiles(self):
        path = os.path.join(ROOT, "SKSE", "Plugins", "StorageUtilData", "MantellaLivingWorld", "observation.json")
        with open(path, encoding="utf-8") as f:
            obs = json.load(f)["int"]
        uncanny = {p["base_id"].zfill(6).lower() for p in self.profiles.values() if p["observation"] >= 4 and len(p["base_id"]) >= 4}
        self.assertTrue(uncanny)
        self.assertLessEqual(uncanny, {k for k, v in obs.items() if v >= 4})
        self.assertTrue(all(v != 2 for v in obs.values()))


if __name__ == "__main__":
    unittest.main()
