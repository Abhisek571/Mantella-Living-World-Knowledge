"""Prompt output for real NPCs from the shipped data: lines that were wrong for the whole game or for a quest stage
(common knowledge about dragons, "never been inside" lines, rumours about inhabited places, quest spoilers, carriage
drivers, the civil war leaders' blocks)."""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import build_profiles as BP  # noqa: E402
from lw_knowledge import hookup as H  # noqa: E402
from lw_knowledge import knowledge as K  # noqa: E402
from lw_knowledge import knows as N  # noqa: E402
from lw_knowledge import lore as L  # noqa: E402

HAS_DB = os.path.exists(L.default_db_path())
OLD_TALES = "nobody alive has seen one"


def profile(name):
    p = K.profile_for(name)
    assert p, name
    return p


def never_inside(p):
    return [l for l in H.identity_lines([p]).splitlines() if "never been inside" in l]


class CommonKnowledge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        H.CHANNEL_DIR = self.tmp.name
        H.reset()
        os.makedirs(os.path.join(self.tmp.name, "npc"))
        with open(os.path.join(self.tmp.name, "npc", "013482.json"), "w", encoding="utf-8") as f:
            json.dump({"string": {"name": "Alvor"}}, f)
        with open(os.path.join(self.tmp.name, "conversation.json"), "w", encoding="utf-8") as f:
            json.dump({"string": {"player": "Player"}, "stringList": {"speakers": ["013482"]}}, f)

    def tearDown(self):
        self.tmp.cleanup()

    def common(self, states):
        if states is not None:
            with open(os.path.join(self.tmp.name, "world.json"), "w", encoding="utf-8") as f:
                json.dump({"quest_state": states}, f)
        return H.system_parts({"background": "Bio."}, {})["common_knowledge"]

    def test_no_old_tales_line_after_dragon_rising(self):
        text = self.common({"MQ101": 2, "MQ102": 2, "MQ103": 2, "MQ104": 2})
        self.assertNotIn(OLD_TALES, text)
        self.assertIn("Helgen", text)

    def test_no_old_tales_line_without_world(self):
        self.assertNotIn(OLD_TALES, self.common(None))

    def test_old_tales_line_before_helgen(self):
        text = self.common({"MQ101": 0, "MQ102": 0, "MQ104": 0})
        self.assertIn(OLD_TALES, text)
        self.assertNotIn("destroyed Helgen", text)


class NeverInside(unittest.TestCase):
    def test_beitild_has_been_inside_her_mine(self):
        p = profile("Beitild")
        self.assertFalse([l for l in never_inside(p) if "Iron-Breaker Mine" in l], never_inside(p))
        self.assertEqual(K.place_level(p, "Iron-Breaker Mine"), 5)

    def test_delphine_has_been_inside_riverwood(self):
        lines = never_inside(profile("Delphine"))
        self.assertFalse([l for l in lines if "Riverwood" in l], lines)

    def test_kodlak_has_been_inside_the_companions(self):
        lines = never_inside(profile("Kodlak Whitemane"))
        self.assertFalse([l for l in lines if "Companions" in l], lines)

    def test_home_and_level_5_never_listed(self):
        p = {"name": "X", "home": "Riverwood", "hold": "Whiterun Hold",
             "ties": [{"place": "Riverwood", "level": 4, "inside": False},
                      {"place": "Sleeping Giant Inn", "level": 5, "inside": False},
                      {"place": "Bleak Falls Barrow", "level": 4, "inside": False}]}
        self.assertEqual(never_inside(p), ["X has never been inside Bleak Falls Barrow."])

    def test_erandur_has_been_inside_nightcaller_temple(self):
        self.assertEqual(never_inside(profile("Erandur")), [])


@unittest.skipUnless(HAS_DB, "lore database not built")
class InhabitedPlaces(unittest.TestCase):
    def look(self, text, name, world=None):
        return " ".join(L.lookup(text, profile(name), 400, world=world))

    def test_high_hrothgar_is_not_an_outlaw_fort(self):
        for name in ("Wilhelm", "Lod"):
            text = self.look("Tell me about High Hrothgar.", name)
            self.assertNotIn("outlaws", text)
            self.assertNotIn("fort", text)

    def test_katariah_is_a_ship_not_a_wreck(self):
        text = self.look("What about the Katariah?", "Sorex Vinius")
        self.assertNotIn("wreck", text)
        self.assertIn("ship", text)

    def test_sea_squall_and_western_watchtower(self):
        self.assertNotIn("wreck", self.look("Is the Sea Squall in port?", "Brina Merilis"))
        self.assertNotIn("outlaws", self.look("Who holds the Western Watchtower?", "Irileth"))


@unittest.skipUnless(HAS_DB, "lore database not built")
class Spoilers(unittest.TestCase):
    def look(self, text, name, world=None):
        return " ".join(L.lookup(text, profile(name), 400, world=world))

    def test_helgen_does_not_name_alduin(self):
        text = self.look("What happened at Helgen?", "Lod")
        self.assertIn("Helgen", text)
        self.assertNotIn("Alduin", text)

    def test_volkihar_clan_does_not_name_harkon(self):
        for name in ("Irnskar Ironhand", "Urag gro-Shub"):
            self.assertNotIn("Harkon", self.look("Tell me about the Volkihar Clan.", name))

    def test_volkihar_known_once_dawnguard_is_over(self):
        text = self.look("Tell me about the Volkihar Clan.", "Urag gro-Shub", world={"quests": {"DLC1VQ08": 200}})
        self.assertIn("Harkon", text)

    def test_dawnstar_does_not_tell_how_waking_nightmare_ends(self):
        # a Pale local from outside Dawnstar: level 3 for the city
        text = " ".join(L.lookup("Tell me about Dawnstar.", dict(profile("Frida"), home="Nightgate Inn"), 400))
        self.assertNotIn("Vaermina", text)
        self.assertNotIn("Dragonborn", text)

    def test_tolfdir_mourns_mirabelle_only_in_the_eye_of_magnus(self):
        during_staff = N.knows_block("Tolfdir", "", {"MG07": 1, "MG08": 0})
        self.assertNotIn("Mirabelle", during_staff)
        self.assertIn("Mirabelle", N.knows_block("Tolfdir", "", {"MG07": 2, "MG08": 1}))


class CarriageDrivers(unittest.TestCase):
    def test_carriage_drivers_are_not_bandits(self):
        for name in ("Bjorlam", "Alfarinn", "Thaer", "Kibell", "Sigaar"):
            p = profile(name)
            self.assertEqual(p["profession"], "carriage_driver", name)
            self.assertEqual(p["travel"], "province", name)
            self.assertIn("carriage driver", H.identity_lines([p]))
            self.assertNotIn("bandit", H.identity_lines([p]))

    def test_friendly_factions_are_not_membership(self):
        row = {"name": "Driver", "race": "Nord", "base_id": "", "bio": "", "tags": "whiterun"}
        rec = {"title": "Driver", "town": "Whiterun", "loc": None, "house": None, "store": None, "class": "warrior",
               "factions": ["banditfriendfaction", "carriage system vendors", "friends with predatorfaction"]}
        self.assertEqual(BP.rule_profile(row, rec, {})["profession"], "carriage_driver")
        rec["factions"] = ["banditfriendfaction"]
        self.assertNotEqual(BP.rule_profile(row, rec, {})["profession"], "bandit")

    def test_people_know_the_local_driver(self):
        self.assertEqual(L.people_line("Bjorlam", profile("Adrianne Avenicci")),
                         "Bjorlam is a carriage driver in Whiterun.")


@unittest.skipUnless(HAS_DB, "lore database not built")
class Leaders(unittest.TestCase):
    def test_civil_war_leaders_have_a_block(self):
        for name in ("Jarl Ulfric Stormcloak", "Jarl Elisif the Fair", "Jarl Siddgeir", "Miraak"):
            p = profile(name)
            self.assertTrue(N.knows_block(p["name"], p["base_id"], None), name)

    def test_asking_about_ulfric(self):
        self.assertEqual(L.people_line("Ulfric Stormcloak", profile("Adrianne Avenicci")),
                         "Ulfric Stormcloak rules Eastmarch from Windhelm.")


if __name__ == "__main__":
    unittest.main()
