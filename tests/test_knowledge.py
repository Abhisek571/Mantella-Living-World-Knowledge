import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from lw_knowledge import knowledge as K  # noqa: E402

BARROW = {"name": "Bleak Falls Barrow", "hold": "Falkreath Hold", "kind": "dungeon"}
RIVERWOOD = {"name": "Riverwood", "hold": "Whiterun Hold", "kind": "town"}
WHITERUN = {"name": "Whiterun", "hold": "Whiterun Hold", "kind": "city"}
DAWNSTAR = {"name": "Dawnstar", "hold": "The Pale", "kind": "city"}
WINDHELM = {"name": "Windhelm", "hold": "Eastmarch", "kind": "city"}
MARKARTH = {"name": "Markarth", "hold": "The Reach", "kind": "city"}
FORT = {"name": "Fort Greymoor", "hold": "Whiterun Hold", "kind": "fort"}
CYRODIIL = {"name": "Cyrodiil", "province": "Cyrodiil", "kind": "province"}
DIMHOLLOW = {"name": "Dimhollow Crypt", "hold": "The Pale", "kind": "dungeon"}


def profile(**kw):
    p = {"home": None, "hold": None, "origin_province": "Skyrim", "profession": "commoner",
         "standing": "common", "travel": "home", "era": "current", "ties": [],
         "observation": 2, "education": 2}
    p.update(kw)
    return p


CAMILLA = profile(home="Riverwood", hold="Whiterun Hold", origin_province="Cyrodiil",
                  profession="merchant", ties=[
                      {"place": "Riverwood Trader", "level": 5, "inside": True},
                      {"place": "Bleak Falls Barrow", "level": 4, "inside": False}])
GUARD = profile(home="Whiterun", hold="Whiterun Hold", profession="guard")
FARENGAR = profile(home="Whiterun", hold="Whiterun Hold", profession="court_wizard", education=5,
                   ties=[{"topic": "dragonstone", "level": 5, "inside": True}])
COURIER = profile(home="Whiterun", hold="Whiterun Hold", profession="courier", travel="province")
SERANA = profile(home=None, hold=None, profession="vampire", era="ancient", education=4,
                 ties=[{"place": "Castle Volkihar", "level": 5, "inside": True},
                       {"place": "Dimhollow Crypt", "level": 5, "inside": True}])


class PlaceLevels(unittest.TestCase):
    def test_camilla_barrow_4_outside(self):
        self.assertEqual(K.place_level(CAMILLA, BARROW), 4)

    def test_camilla_barrow_never_5_without_inside(self):
        p = profile(home="Riverwood", hold="Whiterun Hold",
                    ties=[{"place": "Bleak Falls Barrow", "level": 5, "inside": False}])
        self.assertEqual(K.place_level(p, BARROW), 4)

    def test_camilla_workplace_5_inside(self):
        self.assertEqual(K.place_level(CAMILLA, "Riverwood Trader"), 5)

    def test_guard_barrow_2(self):
        self.assertEqual(K.place_level(GUARD, BARROW), 2)

    def test_own_town_4(self):
        self.assertEqual(K.place_level(CAMILLA, RIVERWOOD), 4)

    def test_own_hold_3(self):
        p = profile(home="Riverwood", hold="Whiterun Hold", profession="farmer")
        self.assertEqual(K.place_level(p, WHITERUN), 3)

    def test_neighbour_2_far_1(self):
        p = profile(home="Riverwood", hold="Whiterun Hold", profession="farmer")
        self.assertEqual(K.place_level(p, DAWNSTAR), 2)
        p2 = profile(home="Markarth", hold="The Reach", profession="farmer")
        self.assertEqual(K.place_level(p2, WINDHELM), 1)

    def test_merchant_bonus_on_trade_towns(self):
        p = profile(home="Markarth", hold="The Reach", profession="merchant")
        self.assertEqual(K.place_level(p, WINDHELM), 2)

    def test_soldier_bonus_on_forts(self):
        p = profile(home="Whiterun", hold="Whiterun Hold", profession="soldier")
        self.assertEqual(K.place_level(p, FORT), 4)

    def test_origin_province_3(self):
        self.assertEqual(K.place_level(CAMILLA, CYRODIIL), 3)
        self.assertEqual(K.place_level(GUARD, CYRODIIL), 1)

    def test_traveller_plus_one_on_routes(self):
        p = profile(home="Markarth", hold="The Reach", profession="farmer", travel="province")
        self.assertEqual(K.place_level(p, WINDHELM), 2)
        p2 = profile(home="Markarth", hold="The Reach", profession="farmer", travel="regional")
        self.assertEqual(K.place_level(p2, WHITERUN), 3)

    def test_courier_settlements_3_everywhere(self):
        self.assertEqual(K.place_level(COURIER, MARKARTH), 3)
        self.assertEqual(K.place_level(COURIER, DAWNSTAR), 3)

    def test_level_capped_at_4_without_tie(self):
        p = profile(home="Whiterun", hold="Whiterun Hold", profession="merchant", travel="province")
        self.assertEqual(K.place_level(p, WHITERUN), 4)

    def test_ancient_capped_2_except_ties(self):
        self.assertEqual(K.place_level(SERANA, DIMHOLLOW), 5)
        self.assertLessEqual(K.place_level(SERANA, WHITERUN), 2)

    def test_unknown_place_string_level_1(self):
        self.assertEqual(K.place_level(GUARD, "Nowhere In Particular"), 1)

    def test_bad_profile_never_raises(self):
        self.assertEqual(K.place_level({}, BARROW), 1)
        self.assertEqual(K.place_level(None, None), 1)


class TopicLevels(unittest.TestCase):
    def test_farengar_dragonstone_topic_5(self):
        self.assertEqual(K.topic_level(FARENGAR, "dragonstone"), 5)

    def test_topic_tie_5_needs_inside(self):
        p = profile(ties=[{"topic": "dragonstone", "level": 5, "inside": False}])
        self.assertEqual(K.topic_level(p, "dragonstone"), 4)

    def test_courier_roads_3(self):
        self.assertEqual(K.topic_level(COURIER, "roads"), 3)

    def test_guard_local_crime_bonus(self):
        self.assertGreater(K.topic_level(GUARD, "local_crime"), K.topic_level(CAMILLA, "local_crime"))

    def test_scholar_magic_bonus(self):
        self.assertGreaterEqual(K.topic_level(FARENGAR, "magic"), 3)

    def test_serana_recent_events_capped(self):
        self.assertEqual(K.topic_level(SERANA, "civil_war"), 1)
        self.assertEqual(K.topic_level(SERANA, "dragons_return"), 1)
        self.assertGreaterEqual(K.topic_level(SERANA, "vampires"), 3)

    def test_unknown_topic_level_1(self):
        self.assertEqual(K.topic_level(GUARD, "some_unheard_topic"), 1)

    def test_levels_in_range(self):
        for p in (CAMILLA, GUARD, FARENGAR, COURIER, SERANA, {}):
            for t in ("roads", "trade", "magic", "civil_war", "dragonstone", "x"):
                self.assertIn(K.topic_level(p, t), range(1, 6))


if __name__ == "__main__":
    unittest.main()
