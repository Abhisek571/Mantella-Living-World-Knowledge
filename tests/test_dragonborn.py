import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from lw_knowledge import dragonborn as D  # noqa: E402

WHITERUN = {"name": "Hulda", "home": "Whiterun", "hold": "Whiterun Hold", "travel": "home"}
REACH = {"name": "Farmer", "home": "Markarth", "hold": "The Reach", "travel": "home"}
TRAVELLER = dict(REACH, travel="province")


class Dragonborn(unittest.TestCase):
    def test_nothing_before_dragon_rising(self):
        self.assertEqual(D.line({"MQ104": 1}, WHITERUN, "Player"), "")
        self.assertEqual(D.line(None, WHITERUN, "Player"), "")

    def test_after_dragon_rising_whiterun_knows_the_name(self):
        line = D.line({"MQ104": 2}, WHITERUN, "Player")
        self.assertIn("Player", line)
        self.assertIn("dragon", line.lower())

    def test_after_dragon_rising_far_away_only_rumours(self):
        line = D.line({"MQ104": 2}, REACH, "Player")
        self.assertNotIn("Player", line)
        self.assertIn("Whiterun", line)
        self.assertIn("Player", D.line({"MQ104": 2}, TRAVELLER, "Player"))

    def test_greybeards_summons_heard_everywhere(self):
        line = D.line({"MQ104": 2, "MQ105": 1}, REACH, "Player")
        self.assertIn("Greybeards", line)
        self.assertNotIn("Player", line)

    def test_keep_secret(self):
        self.assertNotIn("Player", D.line({"MQ104": 2, "MQ105": 2}, WHITERUN, "Player", keep_secret=True))

    def test_main_quest_people_know_the_player(self):
        # SCH-8: Arngeir, Delphine, Esbern and the rest dealt with the player as the Dragonborn
        arngeir = {"name": "Arngeir", "home": "High Hrothgar", "hold": "The Rift", "travel": "home"}
        line = D.line({"MQ104": 2, "MQ105": 2}, arngeir, "Player", keep_secret=True)
        self.assertEqual(line, "Player is the Dragonborn; Arngeir knows them as such.")
        esbern = {"name": "Esbern", "home": "Riften", "hold": "The Rift", "travel": "home"}
        self.assertNotIn("Player", D.line({"MQ104": 2, "MQ105": 2, "MQ203": 0}, esbern, "Player"))
        self.assertIn("Player is the Dragonborn", D.line({"MQ104": 2, "MQ105": 2, "MQ203": 1}, esbern, "Player"))
        self.assertTrue(set(q for q, _ in D.KNOWS_PLAYER.values()) <= set(D.QUESTS))

    def test_quests_always_tracked(self):
        self.assertTrue({"MQ104", "MQ105"} <= set(D.QUESTS))


if __name__ == "__main__":
    unittest.main()
