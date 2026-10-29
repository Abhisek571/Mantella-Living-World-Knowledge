"""Build data/profiles.json: one knowledge profile per Mantella character row.

Usage
  python tools/build_profiles.py [--csv skyrim_characters.csv] [--uesp work/uesp.jsonl.gz]

Fields filled by rules (CSV columns, tags, game data from the UESP NPC pages:
town, house, store, class and job factions, matched by base id + name):
  home, hold, origin_province, profession, standing, travel, era, ties,
  observation, education
Fields only a bio can decide (personal ties, inside visits, origin stated in
the bio, unusual observation / education, era) are rated by hand in
data/ratings/batch_*.json; a rating overrides the rule value for that field.

Profiles are keyed like Mantella overrides: name + race + base_id. Rows that
share a key (generic NPCs without a base id) share one profile.
"""
import argparse
import csv
import glob
import gzip
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "server"))

from lw_knowledge.knowledge import HOLDS, norm_hold  # noqa: E402

DEFAULT_CSV = (r"D:\Modlists\NGVO\mods\[NoDelete] Mantella - Bring NPCs to Life with AI\SKSE"
               r"\Plugins\MantellaSoftware\data\Skyrim\skyrim_characters.csv")

PROVINCES = ("Skyrim", "Cyrodiil", "High Rock", "Hammerfell", "Morrowind", "Summerset Isles",
             "Valenwood", "Elsweyr", "Black Marsh", "Orsinium")
RACE_ORIGIN = {
    "nord": "Skyrim", "imperial": "Cyrodiil", "breton": "High Rock", "redguard": "Hammerfell",
    "dunmer": "Morrowind", "dark elf": "Morrowind", "altmer": "Summerset Isles",
    "high elf": "Summerset Isles", "bosmer": "Valenwood", "wood elf": "Valenwood",
    "khajiit": "Elsweyr", "argonian": "Black Marsh", "orsimer": "Skyrim", "orc": "Skyrim",
}
ORIGIN_RE = re.compile(
    r"\b(?:born (?:and raised )?in|hails? from|grew up in|originally from|immigrants? from|"
    r"came (?:to Skyrim )?from|native of|emigrated from|refugees? from|fled)\s+(?:the )?"
    r"(Skyrim|Cyrodiil|High Rock|Hammerfell|Morrowind|Summerset(?: Isles?)?|Alinor|Valenwood|"
    r"Elsweyr|Black Marsh|Orsinium|Vvardenfell)", re.I)

HOLD_TAGS = {
    "haafingar": "Haafingar", "hjaalmarch": "Hjaalmarch", "the_pale": "The Pale", "pale": "The Pale",
    "winterhold": "Winterhold", "the_reach": "The Reach", "reach": "The Reach",
    "whiterun_hold": "Whiterun Hold", "eastmarch": "Eastmarch", "falkreath_hold": "Falkreath Hold",
    "the_rift": "The Rift", "rift": "The Rift", "solstheim": "Solstheim",
}
# Town for each settlement-like tag / UESP town field
SETTLEMENTS = {
    "solitude": "Haafingar", "dragon bridge": "Haafingar", "katla's farm": "Haafingar",
    "morthal": "Hjaalmarch", "stonehills": "Hjaalmarch",
    "dawnstar": "The Pale", "nightgate inn": "The Pale",
    "winterhold": "Winterhold", "college of winterhold": "Winterhold",
    "markarth": "The Reach", "karthwasten": "The Reach", "old hroldan": "The Reach",
    "soljund's sinkhole": "The Reach", "salvius farm": "The Reach", "left hand mine": "The Reach",
    "whiterun": "Whiterun Hold", "riverwood": "Whiterun Hold", "rorikstead": "Whiterun Hold",
    "windhelm": "Eastmarch", "kynesgrove": "Eastmarch", "darkwater crossing": "Eastmarch",
    "mixwater mill": "Eastmarch", "falkreath": "Falkreath Hold", "helgen": "Falkreath Hold",
    "riften": "The Rift", "ivarstead": "The Rift", "shor's stone": "The Rift",
    "raven rock": "Solstheim", "skaal village": "Solstheim", "tel mithryn": "Solstheim",
    "thirsk mead hall": "Solstheim", "high hrothgar": "The Rift",
    "fort dawnguard": "The Rift", "castle volkihar": "Haafingar",
    "largashbur": "The Rift", "dushnikh yal": "The Reach", "mor khazgur": "The Reach",
    "narzulbur": "Eastmarch", "heartwood mill": "The Rift", "anga's mill": "The Pale",
    "half-moon mill": "Falkreath Hold", "goldenglow estate": "The Rift",
    "lakeview manor": "Falkreath Hold", "windstad manor": "Hjaalmarch",
    "heljarchen hall": "The Pale", "frostflow lighthouse": "Winterhold",
}
BRUMA_TAG = "bs_bruma"

# (pattern, profession) checked against name, then factions, class, tags, role text
NAME_RULES = [
    (r"\bcourier\b", "courier"), (r"\b(guard|sentry|watchman|warden|jailor|jailer)\b", "guard"),
    (r"\b(bandit|marauder|outlaw|highwaym[ae]n|thug|brigand|reaver|raider|pirate)\b", "bandit"),
    (r"\b(forsworn|hagraven|briarheart)\b", "bandit"),
    (r"\b(stormcloak|legionnaire|legate|imperial soldier|soldier|sergeant|general|"
     r"quartermaster|penitus oculatus)\b", "soldier"),
    (r"\bthalmor\b", "soldier"), (r"\b(vigilant|dawnguard)\b", "soldier"),
    (r"\b(priest|priestess|acolyte|monk|vigilant of stendarr)\b", "priest"),
    (r"\bvampire\b", "vampire"), (r"\b(necromancer|warlock|witch)\b", "necromancer"),
    (r"\b(mage|wizard|sorcer\w+|conjurer|enchanter|apprentice)\b", "mage"),
    (r"\b(merchant|trader|peddler|vendor|shopkeeper|caravan)\b", "merchant"),
    (r"\bhunter\b", "hunter"), (r"\bminer\b", "miner"), (r"\b(farmer|farmhand)\b", "farmer"),
    (r"\b(beggar|vagrant)\b", "beggar"), (r"\b(child|boy|girl|urchin|orphan|kid)\b", "child"),
    (r"\b(sailor|fisherman|fisher|dockworker|deckhand|ship captain)\b", "sailor"),
    (r"\bbard\b", "bard"), (r"\b(mercenary|sellsword|bodyguard|hired)\b", "mercenary"),
    (r"\b(assassin|dark brotherhood)\b", "thief"), (r"\b(thief|pickpocket|fence|smuggler)\b",
                                                     "thief"),
    (r"\b(lumberjack|laborer|labourer|worker|woodcutter|mill)\b", "laborer"),
    (r"\b(innkeeper|barkeep|bartender|barmaid|server)\b", "innkeeper"),
    (r"\bblacksmith\b", "blacksmith"), (r"\b(alchemist|apothecary|herbalist)\b", "alchemist"),
    (r"\b(dremora|daedr\w+|spirit|ghost|draugr|wraith|spectral|skeleton|atronach|dragon)\b",
     "creature"),
    (r"\b(jarl|high king|high queen)\b", "court"), (r"\b(steward|housecarl|thane)\b", "court"),
    (r"\b(scholar|historian|scribe|librarian|researcher)\b", "scholar"),
    (r"\b(adventurer|treasure hunter|explorer)\b", "adventurer"),
    (r"\b(healer)\b", "priest"), (r"\b(cook|chef|maid|servant|butler)\b", "servant"),
    (r"\b(noble|lady|lord|baron|count|countess)\b", "noble"),
    (r"\b(skooma|addict|drunk)\b", "commoner"), (r"\b(cultist|worshipper)\b", "cultist"),
    (r"\b(prisoner)\b", "commoner"), (r"\b(greybeard)\b", "monk"),
]
FACTION_RULES = [
    ("carriage system vendors", "carriage_driver"), ("ferry system vendors", "sailor"),
    ("jobjarl", "court"), ("jobsteward", "court"), ("housecarl", "court"),
    ("jobcourtwizard", "court_wizard"), ("jobinnkeeper", "innkeeper"), ("jobinnserver", "innkeeper"),
    ("jobapothecary", "alchemist"), ("jobblacksmith", "blacksmith"), ("jobmerchant", "merchant"),
    ("jobfence", "thief"), ("jobpriest", "priest"), ("jobbard", "bard"), ("jobhealer", "priest"),
    ("jobspellvendor", "mage"), ("jobfarmer", "farmer"), ("jobminer", "miner"),
    ("jobfletcher", "merchant"), ("jobfoodvendor", "merchant"), ("caravan", "caravan"),
    ("greybeard", "monk"), ("collegeofwinterhold", "mage"), ("thievesguild", "thief"),
    ("darkbrotherhood", "thief"), ("companions", "mercenary"), ("vampire", "vampire"),
    ("forsworn", "bandit"), ("bandit", "bandit"), ("thalmor", "soldier"),
    ("cwsons", "soldier"), ("cwimperial", "soldier"), ("isguardfaction", "guard"),
    ("guardfaction", "guard"), ("dawnguard", "soldier"), ("blades", "soldier"),
    ("necromancer", "necromancer"), ("warlock", "necromancer"), ("dlc2skaal", "hunter"),
]
# Classes that say what someone does. Thief, Assassin, Nightblade and Soldier are left out: for townsfolk they are only
# how they fight (Faendal's class is Thief, Belethor's Soldier); guilds and factions catch the real ones.
CLASS_RULES = [
    ("pawnbroker", "merchant"), ("food vendor", "merchant"), ("apothecary", "alchemist"),
    ("blacksmith", "blacksmith"), ("farmer", "farmer"), ("miner", "miner"), ("lumberjack",
                                                                            "laborer"),
    ("bandit", "bandit"), ("priest", "priest"), ("monk", "monk"), ("bard", "bard"),
    ("beggar", "beggar"), ("child", "child"), ("vampire", "vampire"), ("forsworn", "bandit"),
    ("conjurer", "mage"), ("sorcerer", "mage"), ("mage", "mage"), ("witchblade", "bandit"),
    ("spell vendor", "mage"), ("tailor", "merchant"), ("fletcher", "merchant"),
    ("ranger", "hunter"), ("scout", "hunter"), ("vigilant", "priest"), ("penitus", "soldier"),
    ("thalmor", "soldier"),
    ("guard", "guard"), ("prisoner", "commoner"),
]
SKILLED_TRAVEL = {"courier": "province", "caravan": "province", "soldier": "regional",
                  "mercenary": "regional", "hunter": "regional", "bard": "regional",
                  "adventurer": "regional", "bandit": "regional", "merchant": "home",
                  "sailor": "province", "thief": "home", "carriage_driver": "province"}
# Factions that only say who someone is friendly with ("BanditFriendFaction": bandits leave carriage drivers alone),
# never what they are.
FRIENDLY_FACTION = re.compile(r"friend")
EDUCATION = {"court_wizard": 5, "scholar": 5, "mage": 4, "priest": 4, "monk": 4, "court": 4,
             "noble": 4, "necromancer": 4, "alchemist": 3, "merchant": 3, "innkeeper": 3,
             "bard": 3, "vampire": 3, "courier": 3, "blacksmith": 2, "soldier": 2, "guard": 2,
             "farmer": 2, "miner": 1, "laborer": 1, "beggar": 1, "child": 1, "bandit": 1,
             "commoner": 2, "servant": 2, "hunter": 2, "sailor": 2, "thief": 2,
             "mercenary": 2, "creature": 2, "cultist": 2, "caravan": 2, "adventurer": 2}
OBSERVATION = {"guard": 3, "hunter": 3, "thief": 3, "court_wizard": 3, "mage": 3, "soldier": 3,
               "vampire": 3, "monk": 3, "bandit": 2, "child": 2, "beggar": 2, "courier": 2,
               "adventurer": 3, "scholar": 3}
LOW_STANDING = {"bandit", "beggar", "thief", "creature"}
HIGH_FAMILIES = re.compile(r"\b(Battle-Born|Gray-Mane|Silver-Blood|Black-Briar|Snow-Shod|"
                           r"Shatter-Shield|Cruel-Sea|Elisif|Balgruuf|Ulfric|Tullius)\b")
ANCIENT_NAMES = {"serana", "valerica", "gelebor", "vyrthur", "durnehviir", "miraak", "alduin",
                 "paarthurnax", "odahviing", "karstaag", "krosis", "vokun", "nahkriin",
                 "morokei", "rahgot", "hevnoraak", "otar the mad", "volsung", "dukaan",
                 "zahkriisos", "ahzidal", "ysgramor", "tsun", "gormlaith golden-hilt",
                 "hakon one-eye", "felldir the old", "jurgen windcaller", "kodlak's spirit",
                 "wuunferth's ghost", "arniel gane", "katria", "ulfr the blind",
                 "the headless horseman", "lucien flavius"}

# Landmarks the locals of a town know from the outside (level 4, never inside by rule).
LOCAL_LANDMARKS = {
    "riverwood": ["Bleak Falls Barrow"],
    "ivarstead": ["Shroud Hearth Barrow", "High Hrothgar"],
    "dawnstar": ["Nightcaller Temple"],
}

# A place someone is tagged with in their own hold is where they live or work (a miner's mine, a Companion's hall, a
# crew's ship), so they have been inside it; except places people keep out of.
OUTSIDE_KINDS = {"dungeon", "cave", "fort", "camp", "nest", "giant_camp", "shipwreck", "tower", "hold",
                 "region"}


MEMBER_PLACES = {"east empire company", "the companions", "thieves guild"}  # tagged = works for it, wherever it is


def been_inside(place, info, own_hold, home):
    if info.get("kind") in OUTSIDE_KINDS:
        return False
    if place.lower() in MEMBER_PLACES or (home and (info.get("town") or "").lower() == home.lower()):
        return True
    hold = norm_hold(info.get("hold")) or settlement_of(info.get("town"))
    if not own_hold:
        return True  # nothing says they live anywhere else (the East Empire Company's dockworkers)
    if hold:
        return hold == own_hold
    return bool(home) and place.lower().startswith(home.lower())  # "Raven Rock Mine" for Raven Rock


def row_key(name, race, base_id):
    return f"{name.strip()}|{race.strip()}|{base_id.strip().upper()}"


def load_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_places():
    try:
        with open(os.path.join(ROOT, "data", "places.json"), encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return {}


def _field(text, name):
    m = re.search(r"^\|[ \t]*" + name + r"[ \t]*=[ \t]*(.*)$", text, re.M)
    if not m:
        return None
    v = m.group(1)
    link = re.search(r"\[\[(?:Skyrim:)?([^|\]]+)(?:\|([^\]]+))?\]\]", v)
    if link:
        return (link.group(2) or link.group(1)).strip()
    v = re.sub(r"\{\{[^}]*\}\}|<[^>]+>", "", v).strip()
    return v or None


def load_uesp_npcs(path):
    """base id (last 6 hex) -> list of {title, town, house, store, class, factions}."""
    out = {}
    if not path or not os.path.exists(path):
        return out
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            t = d.get("text") or ""
            if "{{NPC Summary" not in t[:4000]:
                continue
            for bid in re.findall(r"^\|\s*baseid\s*=\s*([0-9A-Fa-fx]{6,8})", t, re.M):
                rec = {"title": d["title"][7:], "town": _field(t, "town") or _field(t, "city"),
                       "loc": _field(t, "loc"), "house": _field(t, "house"),
                       "store": _field(t, "store"), "class": (_field(t, "class") or "").lower(),
                       "factions": [x.lower() for x in re.findall(r"\{\{Faction\|([^}|]+)", t)]}
                out.setdefault(bid[-6:].upper(), []).append(rec)
    return out


def match_uesp(row, uesp):
    cands = uesp.get(row["base_id"].strip().upper()[-6:]) if row["base_id"].strip() else None
    if not cands:
        return None
    name = row["name"].strip().lower()
    for c in cands:
        if c["title"].lower().split(" (")[0] == name:
            return c
    return None


def first_rule(rules, text):
    for pat, prof in rules:
        if re.search(pat, text):
            return prof
    return None


def role_text(bio):
    m = re.search(r"^(?:Role|Occupation|Profession|Job)\s*:\s*(.+)$", bio, re.M | re.I)
    first = re.split(r"(?<=[.!?])\s", bio.strip(), maxsplit=1)[0]
    return ((m.group(1) + " ") if m else "") + first


def settlement_of(name):
    return SETTLEMENTS.get((name or "").lower())


def rule_profile(row, uesp_rec, places, rating=None):
    name = row["name"].strip()
    lname = name.lower()
    bio = row.get("bio") or ""
    tags = [t.strip().lower() for t in (row.get("tags") or "").split(",") if t.strip()]
    race = (row.get("race") or "").strip().lower()
    p = {}

    # home + hold
    home = hold = None
    if BRUMA_TAG in tags or "bruma" in lname:
        home, p["origin_province"] = "Bruma", "Cyrodiil"
    for t in tags:
        town = t.replace("_", " ")
        if not home and settlement_of(town):
            home = town.title().replace("'S", "'s")
        if not hold and t in HOLD_TAGS:
            hold = HOLD_TAGS[t]
    if uesp_rec:
        for k in ("town", "loc"):
            v = uesp_rec.get(k)
            if not home and v and (settlement_of(v) or (places.get(v, {}).get("kind") in
                                                        ("city", "town", "settlement"))):
                home = v
    if not home:
        m = re.search(r"\b(?:lives|living|resides|works|stationed|found)\s+(?:in|at)\s+(?:the "
                      r"(?:city|town|village) of\s+)?([A-Z][\w']+(?: [A-Z][\w']+)?)", bio)
        if m and settlement_of(m.group(1)):
            home = m.group(1)
    if not home:  # generic rows named after their town: "Whiterun Guard", "Riften City Guard"
        for town in sorted(SETTLEMENTS, key=len, reverse=True):
            if re.match(re.escape(town) + r"\b", lname):
                home = town.title().replace("'S", "'s")
                break
    if home and not hold:
        hold = settlement_of(home) or norm_hold(places.get(home, {}).get("hold"))
    p["home"] = home
    p["hold"] = hold if hold in HOLDS else None

    # profession
    factions = " ".join(f for f in uesp_rec["factions"] if not FRIENDLY_FACTION.search(f)) if uesp_rec else ""
    place_tags = [t for t in tags if not re.search(r"_(quest|status|updates|rank|chosen|left)$", t)]
    species = (row.get("species") or "").lower()
    prof = (first_rule(NAME_RULES, lname)
            or first_rule([(re.escape(a), b) for a, b in FACTION_RULES], factions)
            or first_rule(NAME_RULES, role_text(bio).lower())
            or first_rule([(re.escape(a), b) for a, b in CLASS_RULES],
                          uesp_rec["class"] if uesp_rec else "")
            or first_rule(NAME_RULES, " ".join(place_tags).replace("_", " "))
            or ("creature" if species in ("daedric", "daedra", "dragon", "undead", "beast")
                else "commoner"))
    if species in ("daedric", "daedra", "dragon"):
        prof = "creature"
    if prof == "court" and re.search(r"court wizard|court mage", role_text(bio), re.I):
        prof = "court_wizard"
    if rating and rating.get("profession"):
        prof = rating["profession"]  # derived defaults below follow the rated profession
    p["profession"] = prof

    # origin
    if "origin_province" not in p:
        m = ORIGIN_RE.search(bio)
        if m:
            o = m.group(1).title()
            o = {"Summerset": "Summerset Isles", "Summerset Isle": "Summerset Isles",
                 "Alinor": "Summerset Isles", "Vvardenfell": "Morrowind"}.get(o, o)
            p["origin_province"] = o if o in PROVINCES else "Skyrim"
        else:
            p["origin_province"] = RACE_ORIGIN.get(race, "Skyrim")

    # standing
    if (re.search(r"\b(jarl|high king|high queen|emperor)\b", lname)
            or re.search(r"\b(is|as) the (jarl|high king|high queen)\b|^jarl\b", role_text(bio).lower())):
        standing = "ruler"
    elif prof in ("court", "court_wizard", "noble") or HIGH_FAMILIES.search(name):
        standing = "high"
    elif prof in LOW_STANDING:
        standing = "low"
    else:
        standing = "common"
    p["standing"] = standing

    p["travel"] = SKILLED_TRAVEL.get(prof, "home")
    if re.search(r"\b(travel(s|ling|ing)|wander(s|ing)|roams?|on the road|caravan)\b",
                 role_text(bio), re.I):
        p["travel"] = "regional" if p["travel"] == "home" else p["travel"]
    p["era"] = "ancient" if (lname in ANCIENT_NAMES or species == "dragon") else "current"

    # ties: workplace, house, tagged places
    ties = []

    def add_tie(place, level, inside):
        if places.get(place, {}).get("kind") in ("hold", "region") or norm_hold(place):
            return
        if place and all(t.get("place", "").lower() != place.lower() for t in ties):
            ties.append({"place": place, "level": level, "inside": inside})

    if uesp_rec:
        for k in ("store", "house"):
            v = uesp_rec.get(k)
            if v and v.lower() not in ("none", "n/a"):
                add_tie(v, 5, True)
    for t in place_tags:
        pl = t.replace("_", " ")
        match = next((k for k in places if k.lower() == pl), None)
        if match and match.lower() != (home or "").lower():
            inside = been_inside(match, places[match], p["hold"], home)
            add_tie(match, 5 if inside else 4, inside)
    for head in re.findall(r"^([A-Z][\w' -]{2,40}?) Information\s*:", bio, re.M):
        if head in places and head.lower() != (home or "").lower():
            inside = been_inside(head, places[head], p["hold"], home)
            add_tie(head, 5 if inside else 4, inside)
    for lm in LOCAL_LANDMARKS.get((home or "").lower(), []):
        add_tie(lm, 4, False)
    p["ties"] = ties[:8]

    p["observation"] = OBSERVATION.get(prof, 2)
    p["education"] = EDUCATION.get(prof, 2)
    if standing in ("high", "ruler"):
        p["education"] = max(p["education"], 4)
    return p


def load_ratings(folder):
    ratings = {}
    for path in sorted(glob.glob(os.path.join(folder, "batch_*.json"))):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for key, fields in data.items():
            ratings.setdefault(key, {}).update(fields)
    return ratings


def apply_rating(profile, rating):
    p = dict(profile)
    for k, v in rating.items():
        if k == "add_ties":
            ties = [t for t in p.get("ties", [])
                    if not any(_same_tie(t, n) for n in v)]
            p["ties"] = ties + v
        elif k == "note":
            continue
        else:
            p[k] = v
    return p


def home_tie(tie, home):
    """A tie to the NPC's own home (Delphine and Riverwood, Frea and Skaal Village): they have been inside it."""
    if home and isinstance(tie.get("place"), str) and tie["place"].lower() == home.lower():
        return dict(tie, level=5, inside=True)
    return tie


def _same_tie(a, b):
    for k in ("place", "topic", "npc"):
        if a.get(k) and b.get(k) and a[k].lower() == b[k].lower():
            return True
    return False


def build(csv_path, uesp_path, out_path, ratings_dir):
    rows = load_csv(csv_path)
    places = load_places()
    uesp = load_uesp_npcs(uesp_path)
    ratings = load_ratings(ratings_dir)
    out, stats = {}, {"rows": len(rows), "uesp_matched": 0, "rated": 0, "keys": 0}
    for row in rows:
        key = row_key(row["name"], row["race"], row["base_id"])
        if key in out:
            continue
        rec = match_uesp(row, uesp)
        if rec:
            stats["uesp_matched"] += 1
        rated = key in ratings
        prof = rule_profile(row, rec, places, ratings.get(key))
        if rated:
            prof = apply_rating(prof, ratings[key])
            stats["rated"] += 1
        prof["ties"] = [home_tie(t, prof.get("home")) for t in prof.get("ties", [])]
        out[key] = {"name": row["name"].strip(), "race": row["race"].strip(),
                    "base_id": row["base_id"].strip().upper(), "rated": rated, **prof}
    stats["keys"] = len(out)
    unused = sorted(set(ratings) - set(out))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "match": "name|race|base_id", "profiles": out}, f,
                  ensure_ascii=False, indent=0, sort_keys=True)
    return stats, unused


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=DEFAULT_CSV)
    ap.add_argument("--uesp", default=os.path.join(ROOT, "work", "uesp.jsonl.gz"))
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "profiles.json"))
    ap.add_argument("--ratings", default=os.path.join(ROOT, "data", "ratings"))
    a = ap.parse_args(argv)
    stats, unused = build(a.csv, a.uesp, a.out, a.ratings)
    print(json.dumps(stats))
    if unused:
        print("ratings with no matching row:", unused[:20], file=sys.stderr)


if __name__ == "__main__":
    main()
