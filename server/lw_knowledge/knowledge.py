"""Knowledge levels: turn an NPC profile into a 1-5 level for a place or a topic.

Levels
  1  heard of it (cities, main roads, the big news)
  2  knows the name, where it is, what people say about it
  3  knows it like a local of the hold
  4  knows it well (own town, a personal tie)
  5  has been inside / knows it first hand (only through a tie with inside=true)

Secrets sit above level 5 and never come from a level (see knows_secret).
Every function here returns a safe default instead of raising: bad or missing
profile data gives level 1, never an exception inside Mantella.
"""
import json
import os

MIN_LEVEL, MAX_LEVEL, MAX_WITHOUT_INSIDE = 1, 5, 4

HOLDS = ("Haafingar", "Hjaalmarch", "The Pale", "Winterhold", "The Reach",
         "Whiterun Hold", "Eastmarch", "Falkreath Hold", "The Rift", "Solstheim")

NEIGHBOURS = {
    "Haafingar": {"Hjaalmarch", "The Reach"},
    "Hjaalmarch": {"Haafingar", "The Reach", "Whiterun Hold", "The Pale"},
    "The Pale": {"Hjaalmarch", "Whiterun Hold", "Winterhold", "Eastmarch"},
    "Winterhold": {"The Pale", "Eastmarch"},
    "The Reach": {"Haafingar", "Hjaalmarch", "Whiterun Hold", "Falkreath Hold"},
    "Whiterun Hold": {"Hjaalmarch", "The Pale", "Eastmarch", "The Rift", "Falkreath Hold",
                      "The Reach"},
    "Eastmarch": {"The Pale", "Winterhold", "Whiterun Hold", "The Rift", "Solstheim"},
    "Falkreath Hold": {"The Reach", "Whiterun Hold", "The Rift"},
    "The Rift": {"Falkreath Hold", "Whiterun Hold", "Eastmarch"},
    "Solstheim": {"Eastmarch"},
}

HOLD_ALIASES = {
    "haafingar": "Haafingar", "haafingar hold": "Haafingar", "solitude": "Haafingar",
    "hjaalmarch": "Hjaalmarch", "hjaalmarch hold": "Hjaalmarch", "morthal": "Hjaalmarch",
    "the pale": "The Pale", "pale": "The Pale", "pale hold": "The Pale", "dawnstar": "The Pale",
    "winterhold": "Winterhold", "winterhold hold": "Winterhold",
    "the reach": "The Reach", "reach": "The Reach", "reach hold": "The Reach",
    "markarth": "The Reach",
    "whiterun hold": "Whiterun Hold", "whiterun": "Whiterun Hold",
    "eastmarch": "Eastmarch", "eastmarch hold": "Eastmarch", "windhelm": "Eastmarch",
    "falkreath hold": "Falkreath Hold", "falkreath": "Falkreath Hold",
    "the rift": "The Rift", "rift": "The Rift", "rift hold": "The Rift", "riften": "The Rift",
    "solstheim": "Solstheim", "raven rock": "Solstheim",
}

SETTLEMENT_KINDS = {"city", "town", "village", "settlement", "inn", "store", "house", "farm",
                    "camp_trade", "road"}
TRADE_KINDS = {"city", "town", "village", "settlement", "inn", "store"}
WILD_KINDS = {"cave", "camp", "landmark", "grove", "shack", "mine", "lake", "mountain",
              "wilderness", "shipwreck", "dungeon", "ruin", "tower", "nest", "giant_camp"}
FORT_KINDS = {"fort", "military", "camp_military", "watchtower", "tower"}
TEMPLE_KINDS = {"temple", "shrine"}

# Profession bonus table (roadmap G): +1 on these place kinds / topics.
# scope "hold" = own hold only, "near" = own + neighbouring holds, "all" = everywhere.
PROFESSIONS = {
    "merchant":     {"places": (TRADE_KINDS, "all"), "topics": {"trade", "prices", "roads"}},
    "innkeeper":    {"places": (TRADE_KINDS, "near"), "topics": {"trade", "rumours", "prices"}},
    "caravan":      {"places": (TRADE_KINDS, "all"), "topics": {"trade", "prices", "roads"}},
    "blacksmith":   {"places": (set(), "hold"), "topics": {"smithing", "trade", "prices"}},
    "alchemist":    {"places": (set(), "hold"), "topics": {"alchemy", "trade", "prices"}},
    "guard":        {"places": (WILD_KINDS | FORT_KINDS, "hold"),
                     "topics": {"local_crime", "law", "bandits"}},
    "soldier":      {"places": (FORT_KINDS, "all"), "topics": {"civil_war", "war", "forts"}},
    "hunter":       {"places": (WILD_KINDS, "near"), "topics": {"wilderness", "animals"}},
    "priest":       {"places": (TEMPLE_KINDS, "all"), "topics": {"religion", "divines", "daedra"}},
    "court":        {"places": ({"city", "palace"}, "all"),
                     "topics": {"politics", "civil_war", "court"}},
    "court_wizard": {"places": ({"city", "palace"}, "hold"),
                     "topics": {"politics", "magic", "history", "court"}},
    "mage":         {"places": (set(), "hold"), "topics": {"magic", "history", "daedra"}},
    "scholar":      {"places": ({"ruin"}, "all"), "topics": {"history", "magic", "lore"}},
    "bard":         {"places": (TRADE_KINDS, "near"), "topics": {"history", "lore", "rumours"}},
    "courier":      {"places": (set(), "all"), "topics": {"roads"}},
    "thief":        {"places": (TRADE_KINDS, "hold"), "topics": {"local_crime", "black_market"}},
    "bandit":       {"places": (WILD_KINDS | FORT_KINDS, "hold"), "topics": {"bandits", "roads"}},
    "mercenary":    {"places": (FORT_KINDS | WILD_KINDS, "near"), "topics": {"war", "bandits"}},
    "miner":        {"places": ({"mine"}, "near"), "topics": {"mining"}},
    "farmer":       {"places": ({"farm"}, "near"), "topics": {"farming"}},
    "sailor":       {"places": ({"dock", "port", "ship", "shipwreck"}, "all"), "topics": {"sea"}},
    "vampire":      {"places": (set(), "hold"), "topics": {"vampires"}},
    "necromancer":  {"places": ({"ruin", "dungeon"}, "near"), "topics": {"magic", "necromancy"}},
    "cultist":      {"places": ({"shrine"}, "all"), "topics": {"daedra"}},
    "monk":         {"places": (set(), "hold"), "topics": {"thuum", "dragons", "history"}},
    "adventurer":   {"places": (WILD_KINDS | {"ruin"}, "near"), "topics": {"ruins", "monsters"}},
}
# Floors: what a profession knows first hand regardless of other rules.
TOPIC_FLOORS = {("courier", "roads"): 3, ("vampire", "vampires"): 4, ("monk", "thuum"): 4,
                ("mage", "magic"): 3, ("court_wizard", "magic"): 3, ("priest", "religion"): 3}
PROFESSION_ALIASES = {"steward": "court", "jarl": "court", "housecarl": "court", "thane": "court",
                      "noble": "court", "trader": "merchant", "shopkeeper": "merchant",
                      "fence": "thief", "assassin": "thief", "wizard": "mage",
                      "greybeard": "monk", "legionnaire": "soldier", "stormcloak": "soldier",
                      "carriage_driver": "courier"}  # drives the roads between every hold

# Topics: base level for an ordinary Skyrim local; era "4E" = recent events.
TOPICS = {
    "roads":          {"base": 2},
    "trade":          {"base": 2},
    "prices":         {"base": 2},
    "rumours":        {"base": 2},
    "local_crime":    {"base": 2},
    "law":            {"base": 2},
    "bandits":        {"base": 2},
    "wilderness":     {"base": 1},
    "animals":        {"base": 2},
    "religion":       {"base": 2},
    "divines":        {"base": 2},
    "daedra":         {"base": 1, "scholarly": True},
    "politics":       {"base": 2, "era": "4E"},
    "court":          {"base": 1},
    "civil_war":      {"base": 2, "era": "4E"},
    "war":            {"base": 2, "era": "4E"},
    "great_war":      {"base": 2, "era": "4E"},
    "thalmor":        {"base": 2, "era": "4E"},
    "dragons_return": {"base": 2, "era": "4E"},
    "dragonborn":     {"base": 1, "era": "4E"},
    "dragons":        {"base": 1, "scholarly": True},
    "thuum":          {"base": 1, "scholarly": True},
    "magic":          {"base": 1, "scholarly": True},
    "alchemy":        {"base": 1, "scholarly": True},
    "history":        {"base": 1, "scholarly": True},
    "lore":           {"base": 1, "scholarly": True},
    "ruins":          {"base": 1, "scholarly": True},
    "vampires":       {"base": 1},
    "necromancy":     {"base": 1, "scholarly": True},
    "smithing":       {"base": 1},
    "mining":         {"base": 1},
    "farming":        {"base": 2},
    "sea":            {"base": 1},
    "black_market":   {"base": 1},
    "monsters":       {"base": 1},
    "forts":          {"base": 1},
    "dwemer":         {"base": 1, "scholarly": True},
    "elder_scrolls":  {"base": 1, "scholarly": True},
    "all_maker":      {"base": 1},
}

_PLACES = None
_DATA_DIR = None


def data_dir():
    """Shipped layout: extensions/lw_knowledge/data; repo layout: <repo>/data."""
    global _DATA_DIR
    if _DATA_DIR is None:
        here = os.path.dirname(os.path.abspath(__file__))
        env = os.environ.get("LW_KNOWLEDGE_DATA")
        for cand in (env, os.path.join(here, "data"),
                     os.path.join(os.path.dirname(os.path.dirname(here)), "data")):
            if cand and os.path.isdir(cand):
                _DATA_DIR = cand
                break
        else:
            _DATA_DIR = os.path.join(here, "data")
    return _DATA_DIR


def _load_json(name, default):
    try:
        with open(os.path.join(data_dir(), name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def places():
    global _PLACES
    if _PLACES is None:
        raw = _load_json("places.json", {})
        _PLACES = {k.lower(): v for k, v in raw.items()} if isinstance(raw, dict) else {}
    return _PLACES


def norm_hold(h):
    if not h or not isinstance(h, str):
        return None
    return HOLD_ALIASES.get(h.strip().lower(), h.strip() if h.strip() in HOLDS else None)


def norm_profession(p):
    if not p or not isinstance(p, str):
        return "commoner"
    p = p.strip().lower().replace(" ", "_")
    return PROFESSION_ALIASES.get(p, p)


def resolve_place(place):
    """Accept a place dict or a name; return dict {name, hold, town, kind, province}."""
    if isinstance(place, dict):
        info = dict(place)
        name = str(info.get("name") or "")
        known = places().get(name.lower(), {})
        for k, v in known.items():
            info.setdefault(k, v)
    elif isinstance(place, str):
        name = place
        info = dict(places().get(place.lower(), {}))
    else:
        return {"name": "", "hold": None, "kind": None}
    info["name"] = name
    info["hold"] = norm_hold(info.get("hold"))
    return info


def _clamp(n):
    return max(MIN_LEVEL, min(MAX_LEVEL, int(n)))


def _ties(profile, key):
    out = {}
    for t in (profile.get("ties") or []):
        if isinstance(t, dict) and isinstance(t.get(key), str):
            out[t[key].lower()] = t
    return out


def _tie_level(tie):
    try:
        lvl = _clamp(tie.get("level", 4))
    except (TypeError, ValueError):
        lvl = 4
    if lvl > MAX_WITHOUT_INSIDE and not tie.get("inside"):
        lvl = MAX_WITHOUT_INSIDE
    return lvl


def _in_scope(scope, own_hold, place_hold):
    if scope == "all":
        return True
    if not own_hold or not place_hold:
        return False
    if scope == "hold":
        return place_hold == own_hold
    return place_hold == own_hold or place_hold in NEIGHBOURS.get(own_hold, ())


def place_level(profile, place):
    """1-5 knowledge of a place for this profile. Never raises."""
    try:
        return _place_level(profile if isinstance(profile, dict) else {}, place)
    except Exception:  # noqa: BLE001 - Mantella must never crash on bad data
        return MIN_LEVEL


def _place_level(profile, place):
    info = resolve_place(place)
    name = info["name"].lower()
    if not name:
        return MIN_LEVEL
    tie = _ties(profile, "place").get(name)
    if tie:
        return _tie_level(tie)

    kind = (info.get("kind") or "").lower()
    province = info.get("province")
    origin = profile.get("origin_province")
    if province and province != "Skyrim" and not info.get("hold"):
        return 3 if origin and origin == province else MIN_LEVEL

    home = (profile.get("home") or "").lower()
    own_hold = norm_hold(profile.get("hold"))
    place_hold = info.get("hold")
    town = (info.get("town") or "").lower()

    if home and (name == home or town == home):
        level = 4
    elif own_hold and place_hold == own_hold:
        level = 3
    elif own_hold and place_hold in NEIGHBOURS.get(own_hold, ()):
        level = 2
    else:
        level = 1

    prof = norm_profession(profile.get("profession"))
    rule = PROFESSIONS.get(prof)
    if rule:
        kinds, scope = rule["places"]
        if kind in kinds and _in_scope(scope, own_hold, place_hold):
            level += 1

    travel = profile.get("travel") or "home"
    if kind in SETTLEMENT_KINDS:
        if travel == "province":
            level += 1
        elif travel == "regional" and _in_scope("near", own_hold, place_hold):
            level += 1
        if prof == "courier":
            level = max(level, 3)

    level = min(level, MAX_WITHOUT_INSIDE)
    if profile.get("era") == "ancient":
        level = min(level, 2)
    return _clamp(level)


def topic_level(profile, topic):
    """1-5 knowledge of a topic for this profile. Never raises."""
    try:
        return _topic_level(profile if isinstance(profile, dict) else {}, topic)
    except Exception:  # noqa: BLE001
        return MIN_LEVEL


def _topic_level(profile, topic):
    if not isinstance(topic, str) or not topic:
        return MIN_LEVEL
    tid = topic.strip().lower().replace(" ", "_")
    info = TOPICS.get(tid, {"base": 1})
    recent_capped = profile.get("era") == "ancient" and info.get("era") == "4E"

    tie = _ties(profile, "topic").get(tid)
    if tie:
        level = _tie_level(tie)
        return MIN_LEVEL if recent_capped and not tie.get("inside") else level

    level = info.get("base", 1)
    prof = norm_profession(profile.get("profession"))
    rule = PROFESSIONS.get(prof)
    if rule and tid in rule["topics"]:
        level += 1
    level = max(level, TOPIC_FLOORS.get((prof, tid), 0))
    try:
        edu = int(profile.get("education") or 2)
    except (TypeError, ValueError):
        edu = 2
    if info.get("scholarly") and edu >= 4:
        level += 1
    if profile.get("standing") in ("high", "ruler") and tid in ("politics", "court"):
        level += 1
    level = min(level, MAX_WITHOUT_INSIDE)
    if recent_capped:
        level = MIN_LEVEL
    return _clamp(level)


# ---------------------------------------------------------------- secret tier
_SECRETS = None


def secrets():
    """{id: secret} from data/secrets.json; {} if missing or broken."""
    global _SECRETS
    if _SECRETS is None:
        raw = _load_json("secrets.json", [])
        _SECRETS = {}
        if isinstance(raw, list):
            for s in raw:
                if isinstance(s, dict) and isinstance(s.get("id"), str):
                    _SECRETS[s["id"]] = s
    return _SECRETS


def _names(seq):
    return {n.strip().lower() for n in (seq or []) if isinstance(n, str)}


def knows_secret(name, secret, world):
    """True only if the NPC is on the secret's in-on-it list, a reached quest
    stage widens it to them, or the player told them (world["told"][id]).
    Knowledge levels never unlock a secret. Never raises."""
    try:
        if not isinstance(name, str) or not name.strip():
            return False
        s = secret if isinstance(secret, dict) else secrets().get(secret)
        if not s:
            return False
        who = name.strip().lower()
        if who in _names(s.get("in_on_it")):
            return True
        world = world if isinstance(world, dict) else {}
        told = world.get("told") if isinstance(world.get("told"), dict) else {}
        if who in _names(told.get(s.get("id"))):
            return True
        stages = world.get("quests") if isinstance(world.get("quests"), dict) else {}
        for u in s.get("unlock") or []:
            try:
                reached = int(stages.get(u["quest"], -1)) >= int(u["stage"])
            except (TypeError, ValueError, KeyError):
                continue
            if not reached:
                continue
            target = u.get("who", "all")
            if target == "all" or who in _names(target if isinstance(target, list) else []):
                return True
        return False
    except Exception:  # noqa: BLE001
        return False


def known_secrets(name, world):
    """Ids of every secret this NPC knows."""
    return [sid for sid, s in secrets().items() if knows_secret(name, s, world)]


# ---------------------------------------------------------------- profiles
_PROFILES = None


def profiles():
    """{"name|race|base_id": profile} from data/profiles.json; {} if missing."""
    global _PROFILES
    if _PROFILES is None:
        raw = _load_json("profiles.json", {})
        _PROFILES = raw.get("profiles", {}) if isinstance(raw, dict) else {}
    return _PROFILES


def profile_key(name, race, base_id):
    return f"{(name or '').strip()}|{(race or '').strip()}|{(base_id or '').strip().upper()}"


def profile_for(name, race="", base_id=""):
    """Match like Mantella overrides: name + race + base id, then looser fallbacks.
    base_id may be a full 8-digit form id; only the last 6 hex digits are compared."""
    try:
        bid = (base_id or "").strip().upper()
        bid = bid[-6:] if len(bid) > 6 else bid
        table = profiles()
        p = table.get(profile_key(name, race, bid))
        if p is None:
            lname = (name or "").strip().lower()
            # Mantella names some rulers with their title ("Jarl Ulfric Stormcloak"); people ask without it
            same = [v for v in table.values() if v.get("name", "").lower() == lname] or \
                [v for v in table.values() if v.get("name", "").lower() == "jarl " + lname]
            exact = [v for v in same if bid and v.get("base_id") == bid]
            p = (exact or same or [None])[0] if len(exact or same) == 1 or exact else None
        return dict(p) if p else None
    except Exception:  # noqa: BLE001
        return None
