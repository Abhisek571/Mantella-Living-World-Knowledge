import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from lw_knowledge import knowledge as K  # noqa: E402


class Secrets(unittest.TestCase):
    def test_secrets_file_valid(self):
        secrets = K.secrets()
        self.assertGreaterEqual(len(secrets), 5)
        for s in secrets.values():
            self.assertTrue(s["text_pieces"])
            self.assertTrue(s["in_on_it"])
            for u in s["unlock"]:
                self.assertIsInstance(u["stage"], int)
                self.assertTrue(u["quest"])

    def test_in_on_it_knows(self):
        self.assertTrue(K.knows_secret("Esbern", "alduin_raises_dragons", {}))
        self.assertTrue(K.knows_secret("elenwen", "thalmor_prolong_war", None))

    def test_secret_never_from_level(self):
        farengar = {"home": "Whiterun", "hold": "Whiterun Hold", "profession": "court_wizard",
                    "education": 5, "observation": 4, "standing": "high",
                    "ties": [{"topic": "dragons_return", "level": 5, "inside": True},
                             {"topic": "alduin_raises_dragons", "level": 5, "inside": True}]}
        self.assertEqual(K.topic_level(farengar, "alduin_raises_dragons"), 5)
        self.assertFalse(K.knows_secret("Farengar Secret-Fire", "alduin_raises_dragons", {}))

    def test_unlock_after_stage(self):
        before = {"quests": {"MQ106": 150}}
        after = {"quests": {"MQ106": 200}}
        self.assertFalse(K.knows_secret("Delphine", "alduin_raises_dragons_x", after))
        # Delphine is in on it anyway; use the Thalmor plan, which she learns at MQ201 250.
        self.assertFalse(K.knows_secret("Delphine", "thalmor_prolong_war", before))
        self.assertTrue(K.knows_secret("Delphine", "thalmor_prolong_war",
                                       {"quests": {"MQ201": 250}}))
        self.assertFalse(K.knows_secret("Hulda", "alduin_raises_dragons", after))
        self.assertTrue(K.knows_secret("Hulda", "alduin_raises_dragons",
                                       {"quests": {"MQ305": 200}}))

    def test_told_by_player_unlocks_for_that_npc_only(self):
        world = {"told": {"circle_werewolves": ["Ysolda"]}}
        self.assertTrue(K.knows_secret("Ysolda", "circle_werewolves", world))
        self.assertFalse(K.knows_secret("Carlotta Valentia", "circle_werewolves", world))
        self.assertFalse(K.knows_secret("Ysolda", "mercer_betrayal", world))

    def test_bad_input_is_false(self):
        self.assertFalse(K.knows_secret(None, "alduin_raises_dragons", {}))
        self.assertFalse(K.knows_secret("Esbern", None, {}))
        self.assertFalse(K.knows_secret("Esbern", "nope", {"quests": "bad"}))
        self.assertFalse(K.knows_secret("Hulda", "alduin_raises_dragons",
                                        {"quests": {"MQ305": "x"}}))

    def test_secret_dict_accepted(self):
        s = {"id": "x", "in_on_it": ["A"], "unlock": [{"quest": "Q", "stage": 5, "who": ["B"]}]}
        self.assertTrue(K.knows_secret("a", s, {}))
        self.assertTrue(K.knows_secret("B", s, {"quests": {"Q": 10}}))
        self.assertFalse(K.knows_secret("C", s, {"quests": {"Q": 10}}))

    def test_known_secrets_list(self):
        ids = K.known_secrets("Karliah", {})
        self.assertIn("mercer_betrayal", ids)
        self.assertNotIn("alduin_raises_dragons", ids)


if __name__ == "__main__":
    unittest.main()
