import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "server"))

import build_lore as B  # noqa: E402

RULE = ("You only know what your background, memories and knowledge lines say, plus what "
        "anyone in Skyrim would know. You do not know quest secrets, puzzles, hidden mechanisms "
        "or places you have never been. When asked about such things, deflect in your own "
        "words.")


def read(*parts):
    with open(os.path.join(ROOT, "data", *parts), encoding="utf-8") as f:
        return f.read()


class DataFiles(unittest.TestCase):
    def test_knowledge_rule_exact_one_line(self):
        with open(os.path.join(ROOT, "SKSE", "Plugins", "MantellaSoftware", "data", "prompt_rules", "30_knowledge.txt"), encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(text.strip(), RULE)
        self.assertEqual(len(text.strip().splitlines()), 1)

    def test_common_knowledge_size(self):
        # cached, but sent with every NPC; only one Helgen line and one war line are sent
        from lw_knowledge import hookup as H
        for states in (None, {"CWFinale": 2, "war_side": "Legion"}, {"CWFinale": 2, "war_side": "Stormcloaks"}):
            self.assertLessEqual(B.tokens(H.common_knowledge(states)), 350, states)

    def test_common_knowledge_has_no_secrets(self):
        text = read("common_knowledge.txt")
        for sid, rx in B.SECRET_RE.items():
            self.assertIsNone(rx.search(text), sid)

    def test_no_cut_map_markers(self):
        # Skyrim.esm 0F5FD2-0F5FF5 (except 0F5FEF) are unused markers parked in the WarehouseMapMarkers cell
        import json
        with open(os.path.join(ROOT, "SKSE", "Plugins", "StorageUtilData", "MantellaLivingWorld", "markers.json"),
                  encoding="utf-8") as f:
            markers = json.load(f)
        self.assertEqual(set(markers["int"]), {k for k in markers["string"] if not k.startswith("gate:")})
        cut = [k for k, v in markers["int"].items()
               if markers["string"][k].lower() == "skyrim.esm" and 0x0F5FD2 <= v <= 0x0F5FF5 and v != 0x0F5FEF]
        self.assertEqual(cut, [])
        for name in ("twisted root cave", "riverwatch", "eye of markarth", "kyneswatch"):
            self.assertNotIn(name, markers["int"])

    def test_secret_map_places_gated(self):
        # SCH-10: secret places are marked only once their quest has started
        import json
        import re
        with open(os.path.join(ROOT, "SKSE", "Plugins", "StorageUtilData", "MantellaLivingWorld", "markers.json"),
                  encoding="utf-8") as f:
            markers = json.load(f)
        gates = {k[5:]: v for k, v in markers["string"].items() if k.startswith("gate:")}
        for place in ("sky haven temple", "dark brotherhood sanctuary", "dawnstar sanctuary", "castle volkihar",
                      "forgotten vale", "nightingale hall", "twilight sepulcher", "thalmor embassy", "redwater den",
                      "reachcliff secret entrance"):
            self.assertIn(place, gates)
        for place, quest in gates.items():
            self.assertIn(place, markers["int"])
            self.assertRegex(quest, r"^[A-Za-z0-9]+$")
        with open(os.path.join(ROOT, "Source", "Scripts", "MLWK_Map.psc"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn('"gate:" + placeName', text)
        self.assertIn("does not know the way there", text)
        self.assertIn("could not mark that place on the map", text)  # SCH-11: no silent miss
        self.assertNotIn("markedThisTalk", text)  # one mark per NPC per game day instead
        self.assertTrue(re.search(r'StorageUtil\.SetIntValue\(speaker, MARKED_DAY', text))

    def test_map_event_not_wrapped_in_parentheses(self):
        # Mantella already shows MantellaAddEvent lines in parentheses
        with open(os.path.join(ROOT, "Source", "Scripts", "MLWK_Map.psc"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn('Send(who + " marked "', text)
        self.assertNotIn('Send("("', text)


if __name__ == "__main__":
    unittest.main()
