"""Build data/lore.sqlite (FTS5) and data/places.json from the UESP and Fandom wiki dumps.

Usage
  python tools/build_lore.py --uesp <uespwiki-...-current.xml.bz2> --fandom <elderscrolls_pages_current.xml.7z>
  python tools/build_lore.py --from-work        (reuse work/*.jsonl.gz from an earlier run)

Steps: stream both dumps (Skyrim pages only) -> strip markup -> drop non-lore
sections (bugs, notes, console, achievements, behind the scenes, stats and
item tables) -> merge duplicate titles (UESP first, Fandom fills gaps) -> cut
into facts of at most 80 tokens tagged place / npc / topic / era / depth 1-5 /
inside / secret -> SQLite with an FTS5 index.

Only stdlib. The wiki text itself is not shipped with the repo; the build
tool is.
"""
import argparse
import gzip
import html
import json
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "server"))

import wikidump  # noqa: E402
from lw_knowledge.knowledge import norm_hold  # noqa: E402

MAX_FACT_TOKENS = 80
# Per-article caps by depth band keep the whole database near the 1M token target.
ARTICLE_CAPS = {"place": 700, "npc": 380, "topic": 450, "creature": 150}

DROP_SECTIONS = re.compile(
    r"bug|note|console|achievement|behind the scenes|trivia|gallery|appearance|see also|"
    r"reference|quest stage|journal|dialogue|quote|conversation|merchandise|inventory|"
    r"equipment|notable item|character data|related quest|^quests?$|map|external|ingredient|"
    r"skill|stat|enem|creature|treasure|loot|issue|spell|leveled|data|trophies|"
    r"walkthrough|puzzle solution|items?$|books?$|footnote|patch|unofficial|update|"
    r"interactions|services|follower|marriage|combat|perks?|abilities|effects?$|"
    r"sources|availability|crafting|smithing|enchant|location id|ids?$|other|variants|"
    r"bounty|crime|resources|navigation|tamriel|images|video|survival", re.I)
OUTSIDE_SECTIONS = re.compile(r"^(background|history|exterior|overview|location|lore|"
                              r"description of the area|surroundings|legend|origin)", re.I)

KIND_MAP = {
    "home": "house", "house": "house", "nordic dwelling": "house", "cellar": "building",
    "cave": "cave", "nordic ruin": "dungeon", "dwarven ruin": "dungeon", "barrow": "dungeon",
    "ruins": "dungeon", "ayleid ruin": "dungeon", "root tunnel": "dungeon", "dungeon": "dungeon",
    "nordic tomb": "dungeon", "dwemer ruin": "dungeon", "falmer hive": "dungeon",
    "store": "store", "shop": "store", "military fort": "fort", "fort": "fort",
    "landmark": "landmark", "standing stone": "landmark", "pass": "landmark",
    "clearing": "landmark", "all-maker stone": "landmark", "body of water": "landmark",
    "cemetery": "landmark", "lighthouse": "landmark", "mine": "mine", "inn": "inn",
    "shack": "shack", "settlement": "settlement", "orc stronghold": "settlement",
    "town": "town", "village": "town", "city": "city", "castle": "palace", "palace": "palace",
    "farm": "farm", "wheat mill": "farm", "wood mill": "farm", "giant camp": "giant_camp",
    "camp": "camp", "bandit camp": "camp", "stormcloak camp": "camp_military",
    "imperial camp": "camp_military", "dragon lair": "nest", "imperial tower": "tower",
    "nordic tower": "tower", "tower": "tower", "shipwreck": "shipwreck", "ship": "shipwreck",
    "temple": "temple", "daedric shrine": "shrine", "shrine": "shrine", "guild": "guild",
    "guild hall": "guild", "docks": "dock", "barracks": "military", "jail": "military",
    "barracks / jail": "military", "hold": "hold", "worldspace": "region", "library": "building",
    "building": "building", "stable": "building", "forge": "building", "grove": "grove",
    "black book": "dungeon", "hagraven nest": "camp", "vampire lair": "dungeon",
    "warlock lair": "dungeon", "draugr crypt": "dungeon", "spriggan grove": "grove",
}
INSIDE_KINDS = {"dungeon", "cave", "fort", "mine", "nest", "tower", "shipwreck", "camp",
                "giant_camp", "house", "palace", "temple", "shrine", "guild", "inn", "store",
                "building", "military", "camp_military", "shack"}
# Lead sentences of an enterable place that describe what is inside it.
INSIDE_HINT = re.compile(r"\b(word wall|puzzles?|traps?|pillars?|levers?|claw|chests?|treasure|boss|"
                         r"dragon priest|Dragonstone|Elder Scroll|sarcophag\w*|coffin|"
                         r"overlord|inner|interior|deep(er)? inside|depths|sanctum|"
                         r"hidden|secret|mechanism|door)\b", re.I)
COMMON_KINDS = {"city", "hold", "region"}  # lead line is common knowledge (depth 1)
ANCIENT_KINDS = {"dungeon"}

TOPIC_IDS = {
    "civil war": "civil_war", "great war": "great_war", "thalmor": "thalmor",
    "dragons": "dragons", "dragon": "dragons", "dragonborn": "dragonborn",
    "daedra": "daedra", "vampires": "vampires", "vampire": "vampires", "magic": "magic",
    "divines": "divines", "nine divines": "divines", "imperial legion": "civil_war",
    "stormcloaks": "civil_war", "thu'um": "thuum", "dragon shouts": "thuum",
    "alchemy": "alchemy", "smithing": "smithing", "bandits": "bandits", "werewolves": "monsters",
}

# Facts naming a secret are gated by knows_secret at lookup time.
SECRET_PATTERNS = {
    "alduin_raises_dragons": r"\bAlduin\b.{0,80}\b(resurrect|rais|revive|bring|back to life)|"
                             r"(resurrect|rais|revive)\w*\b.{0,60}\bdragons?\b.{0,40}\bAlduin|"
                             r"\bWorld-Eater\b",
    "thalmor_prolong_war": r"\bThalmor\b.{0,120}\b(prolong|drag on|weaken|asset|dossier)",
    "thalmor_hunt_blades": r"\bEsbern\b.{0,80}\bRatway|\bRatway\b.{0,80}\bEsbern",
    "delphine_is_blade": r"\bDelphine\b.{0,120}\bBlades?\b|\bBlades?\b.{0,120}\bDelphine\b",
    "mercer_betrayal": r"\bMercer\b.{0,160}\b(murder|kill|betray|Gallus|Skeleton Key|vault)",
    "nightingales": r"\bNightingales?\b",
    "circle_werewolves": r"\b(werewol\w*|beast blood|lycanthrop\w*)\b",
    "emperor_contract": r"\bMotierre\b|\bassassinat\w*\b.{0,60}\bEmperor\b|\bEmperor\b.{0,60}"
                        r"\bassassinat\w*",
    "silver_blood_forsworn": r"\bThonar\b.{0,160}\bForsworn\b|\bMadanach\b.{0,160}\bThonar\b",
    "ancano_eye_of_magnus": r"\bAncano\b.{0,160}\bEye of Magnus\b|\bEye of Magnus\b.{0,160}"
                            r"\bAncano\b",
    "tyranny_of_the_sun": r"\bTyranny of the Sun\b|\bblot out the sun\b",
    "miraak_returns": r"\bMiraak\b",
}
SECRET_RE = {k: re.compile(v, re.I | re.S) for k, v in SECRET_PATTERNS.items()}
RECENT_RE = re.compile(r"\b(Stormcloaks?|Imperial Legion|civil war|Ulfric|Tullius|Helgen|"
                       r"4E 20[01]|dragons? (have|has) returned|return of the dragons|"
                       r"Dragonborn)\b", re.I)

COMMON_WORDS = set("""
a an the of and in on at to for from by with as is are was be been it its this that these those
home house farm mine camp cave fort tower inn store shop guard guards bandit bandits dragon dragons
wolf wolves bear bears ice fire frost storm stone stones gold silver iron steel book books
river lake falls pass road roads hill hills mountain peak rock wood woods forest grove spring
north south east west sea ship dock docks hall halls temple shrine college guild war king queen
jarl steward priest priestess mage wizard hunter farmer miner smith merchant thief thieves
mother father brother sister son daughter wife husband man woman boy girl child lady lord
companions blades legion empire emperor skooma mead ale wine bread cheese apple honey salt
horse horses giant giants troll trolls spider spiders skeever skeevers draugr vampire vampires
werewolf ghost ghosts spirit shade daedra prince sword axe bow shield armor arrow arrows
circle moon sun star stars night day dawn dusk old new hope fear peace honor glory light dark
red white black blue green gray grey brown yellow golden silent frozen broken lost hidden
""".split())

HEADING_RE = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$", re.M)
SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(])")


# ------------------------------------------------------------------- markup

def _strip_nested(text, open_s, close_s, keep=None):
    """Remove balanced open_s...close_s blocks; keep(inner) may return replacement text."""
    out, i, n = [], 0, len(text)
    lo, lc = len(open_s), len(close_s)
    while i < n:
        j = text.find(open_s, i)
        if j < 0:
            out.append(text[i:])
            break
        out.append(text[i:j])
        depth, k = 1, j + lo
        while k < n and depth:
            if text.startswith(open_s, k):
                depth += 1
                k += lo
            elif text.startswith(close_s, k):
                depth -= 1
                k += lc
            else:
                k += 1
        inner = text[j + lo:k - lc] if depth == 0 else text[j + lo:]
        if keep:
            out.append(keep(inner))
        i = k
    return "".join(out)


def _template(inner):
    name = inner.split("|", 1)[0].strip().lower()
    if name in ("skyrim", "sr", "game|sr"):
        return "Skyrim"
    if name in ("small", "nowrap", "sic", "nw", "hover", "tooltip") and "|" in inner:
        return inner.split("|", 2)[1]
    return ""


def _link(inner):
    target, _, label = inner.partition("|")
    t = target.strip()
    if re.match(r"(?i)(file|image|category|media)\s*:", t):
        return ""
    if re.match(r"^[a-z]{2}(-[a-z]+)?:", t):  # interlanguage
        return ""
    text = label.split("|")[-1] if label else t
    if not label:
        text = re.sub(r"^[A-Za-z ]+:", "", text)
        text = re.sub(r"\s*\([^)]*\)$", "", text)
    return text.split("#")[-1] if text.startswith("#") else text


def strip_markup(text):
    """MediaWiki text -> plain prose (headings kept as ==X== lines for sectioning)."""
    t = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    t = re.sub(r"<(ref|gallery|noinclude|math|score|imagemap)[^>]*?/>", "", t, flags=re.I)
    t = re.sub(r"<(ref|gallery|noinclude|math|score|imagemap)[^>]*>.*?</\1\s*>", "", t,
               flags=re.S | re.I)
    t = _strip_nested(t, "{|", "|}")
    t = _strip_nested(t, "{{", "}}", _template)
    t = _strip_nested(t, "[[", "]]", _link)
    t = re.sub(r"\[(?:https?|ftp)://\S+\s+([^\]]+)\]", r"\1", t)
    t = re.sub(r"\[(?:https?|ftp)://\S+\]", "", t)
    t = re.sub(r"'{2,}", "", t)
    t = re.sub(r"</?[a-zA-Z][^>]*>", " ", t)
    t = html.unescape(t).replace(" ", " ")
    lines = []
    for line in t.split("\n"):
        s = line.strip()
        if not s:
            lines.append("")
            continue
        if HEADING_RE.match(s):
            lines.append(s)
            continue
        if s[0] in "*#:;":
            s = s.lstrip("*#:; ").strip()
            if len(s.split()) < 8:
                continue
        if s.startswith("|") or s.startswith("!") or s.startswith("__"):
            continue
        lines.append(re.sub(r"\s+", " ", s))
    out = "\n".join(lines)
    out = re.sub(r"\(\s*[,;]?\s*\)", "", out)
    out = re.sub(r" +([,.;:])", r"\1", out)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def sections(plain):
    """[(heading or '', text)] with heading '' for the lead."""
    out, last, head = [], 0, ""
    for m in HEADING_RE.finditer(plain):
        out.append((head, plain[last:m.start()].strip()))
        head, last = m.group(2).strip(), m.end()
    out.append((head, plain[last:].strip()))
    return [(h, s) for h, s in out if s]


def tokens(text):
    return max(1, (len(text) + 3) // 4)


def split_facts(text, max_tokens=MAX_FACT_TOKENS, keep=None):
    facts, cur = [], ""
    for para in text.split("\n"):
        for sent in SENT_RE.split(para.strip()):
            sent = sent.strip()
            if not sent or (keep and not keep(sent)):
                continue
            while tokens(sent) > max_tokens:
                words = sent.split()
                cut = max(1, len(words) * max_tokens // tokens(sent) - 1)
                if cur:
                    facts.append(cur)
                    cur = ""
                facts.append(" ".join(words[:cut]))
                sent = " ".join(words[cut:])
            if cur and tokens(cur + " " + sent) > max_tokens:
                facts.append(cur)
                cur = sent
            else:
                cur = (cur + " " + sent).strip()
        if cur:
            facts.append(cur)
            cur = ""
    return [f for f in facts if len(f.split()) >= 4]


# ------------------------------------------------------------- page parsing

def field(text, *names):
    for n in names:
        m = re.search(r"^\|\s*" + re.escape(n) + r"\s*=\s*(.*)$", text, re.M | re.I)
        if m:
            v = strip_markup(m.group(1)).split("\n")[0]
            v = re.split(r"\s{2,}|<br", v)[0].strip()
            if v:
                return v
    return None


def title_key(title):
    t = re.sub(r"^Skyrim:", "", title)
    t = re.sub(r"\s*\((place|location|npc|character|skyrim|person|creature|city|town|"
               r"dawnguard|dragonborn|hearthfire|skyrim location)\)\s*$", "", t, flags=re.I)
    return t.strip()


def classify(src, title, text):
    """Return (kind, info) or (None, None) for pages we skip."""
    head = text[:3000]
    if re.search(r"\{\{\s*(disambig|Game Book|Book|Mod Header|CC Header|SkyrimMods)", head, re.I):
        return None, None
    if "/" in title or re.search(r"\((quest|test cell|book|item|spell|effect)\)", title, re.I):
        return None, None
    info = {}
    if src == "uesp":
        if "{{Place Summary" in head or "{{City Summary" in head:
            typ = (field(text, "type") or ("City" if "{{City Summary" in head else "")).lower()
            info["place_kind"] = KIND_MAP.get(typ, "landmark")
            reg = field(text, "region", "hold")
            info["hold"] = norm_hold(re.sub(r"\s*\(region\)", "", reg or ""))
            loc = field(text, "city", "town")
            info["town"] = loc
            info["description"] = field(text, "description")
            if not info["hold"]:
                m = re.search(r"in \[\[Skyrim:([^|\]]+)", head)
                info["hold"] = norm_hold(m.group(1)) if m else None
            return "place", info
        if "{{NPC Summary" in head:
            info["town"] = field(text, "town", "city")
            return "npc", info
        if re.search(r"\{\{\s*(Creature Summary)", head):
            return "creature", info
        m = re.match(r"\s*\{\{[Tt]rail2?\|([^}|]+)", text)
        if m:
            trail = m.group(1).strip()
            if trail in ("Factions", "Races", "People", "Disease", "Places"):
                return "topic", info
            if trail == "Creatures":
                return "creature", info
            return None, None
        if re.search(r"\{\{\s*(Quest Header|Effect Summary|Ingredient Summary|Spell Summary|"
                     r"Shout Summary|Skills Summary|Item Summary|Armor Summary|Weapon Summary|"
                     r"Alchemy|Potion|Trail2?)\b", head, re.I):
            return None, None
        if re.match(r"\s*(\{\{(About|Faction Header|Marker Icon|Featured Article|incomplete|"
                    r"cleanup)[^}]*\}\}\s*)*[^{]", text, re.I):
            return "topic", info
        return None, None
    # Fandom
    if re.search(r"\{\{\s*(Skyrim|Dawnguard|Dragonborn|Hearthfire)Characters", head):
        return "npc", info
    if re.search(r"\{\{\s*(Skyrim|Dawnguard|Dragonborn|Hearthfire)Locations", head):
        typ = (field(text, "type") or "").lower()
        info["place_kind"] = KIND_MAP.get(typ, "landmark")
        info["hold"] = norm_hold(field(text, "hold") or "")
        return "place", info
    if re.search(r"\{\{\s*(Skyrim|Dawnguard|Dragonborn)(Creatures|Enemies)", head):
        return "creature", info
    if re.match(r"\s*(\{\{(For|About|Attention|Skyrim)[^}]*\}\}\s*)*[^{]", text):
        if "[[Category:Skyrim: Lore" in text or "[[Category:Skyrim: Factions" in text \
                or "[[Category:Skyrim: Races" in text or "[[Category:Skyrim: Organizations" in text:
            return "topic", info
    return None, None


DIALOGUE_RE = re.compile("^([\"“]|[A-Z][\\w'-]*( [A-Z][\\w'-]*)*: [\"“]|I could |"
                         "I'll |Can you |What )")


META_RE = re.compile(r"\b(you|your|yourself|player|players|the game|game's|in-game|leveled|"
                     r"console|PC|Xbox|PS3|PS4|patch|bug|glitch|for more information|NPCs?|"
                     r"respawns?|loot|lootable|chests?|strongbox|satchel|coin purse|map marker|"
                     r"quest|quests|questline|objective|dialogue|Creation Club|Anniversary "
                     r"Edition|Dragonborn DLC|DLC|Hearthfire|Dawnguard add-on|refid|baseid|"
                     r"this page|category|listed|lists all|test cells?|sandbox|unused|"
                     r"workbench|horse armor|playable|skill|skills|perks?|ammunition)\b",
                     re.I)


def clean_sentence(sent):
    """Keep a sentence only if it is third-person lore, not guide text or dialogue."""
    if sent.count('"') % 2 or sent.count("“") != sent.count("”"):
        return False
    return not is_dialogue(sent)


def is_dialogue(fact):
    if META_RE.search(fact):
        return True
    if DIALOGUE_RE.match(fact) or fact.rstrip().endswith(":"):
        return True
    if re.search(r"(^|[\s\"])(I|I'm|I've|I'd|I'll|me|my|we|We)\b", fact):
        return True
    quoted = sum(len(q) for q in re.findall(r'"[^"]*"|“[^”]*”', fact))
    return quoted > len(fact) * 0.5


def page_facts(kind, info, plain, title=""):
    """[(section, depth, inside, text)] for one article, cheapest/most public first."""
    out = []
    place_kind = info.get("place_kind")
    desc = info.get("description")
    if kind == "place" and desc and title:
        d = desc.rstrip(".")
        d = d[0].lower() + d[1:] if d[:2].istitle() and not d.startswith(title) else d
        lead = f"{title} is {d}." if not d.lower().startswith(title.lower()) else d + "."
        out.append(("", 1 if place_kind in COMMON_KINDS | {"town", "settlement"} else 2, 0,
                    lead[0].upper() + lead[1:]))
    for head, body in sections(plain):
        if head and DROP_SECTIONS.search(head):
            continue
        facts = split_facts(body, keep=clean_sentence)
        if not facts:
            continue
        if not head:
            if kind == "place":
                first = 1 if place_kind in COMMON_KINDS else 2
                rest = 2 if place_kind in COMMON_KINDS or place_kind in ("town", "settlement") \
                    else 3
            elif kind == "npc":
                first, rest = 2, 3
            elif kind == "creature":
                first, rest = 2, 3
            else:
                first, rest = 1, 2
            if out:  # the summary description already gave the lead line
                first = rest
            for i, f in enumerate(facts):
                if kind == "place" and place_kind in INSIDE_KINDS and INSIDE_HINT.search(f):
                    out.append(("", 5, 1, f))
                else:
                    out.append(("", first if i == 0 else rest, 0, f))
            continue
        if kind == "place" and place_kind in INSIDE_KINDS and not OUTSIDE_SECTIONS.match(head):
            for f in facts:
                out.append((head, 5, 1, f))
        elif kind == "npc":
            for f in facts:
                out.append((head, 4, 0, f))
        elif kind == "creature":
            continue
        else:
            for f in facts:
                out.append((head, 3, 0, f))
    return out


def _words(text):
    return {w for w in re.findall(r"[a-z']{4,}", text.lower())}


def tag_era(text, info):
    if RECENT_RE.search(text):
        return "4E"
    return ""


def tag_secret(text):
    for sid, rx in SECRET_RE.items():
        if rx.search(text):
            return sid
    return ""


# ------------------------------------------------------------------- build

def load_work(path):
    pages, redirects = [], {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d["title"] == "__redirects__":
                redirects.update(d["redirects"])
            else:
                pages.append(d)
    return pages, redirects


def collect(pages_by_src):
    """Merge by title key: UESP wins, Fandom fills articles UESP lacks (and missing holds)."""
    arts = {}
    for src in ("uesp", "fandom"):
        for d in pages_by_src.get(src, []):
            kind, info = classify(src, d["title"], d["text"])
            if not kind:
                continue
            key = title_key(d["title"])
            if not key:
                continue
            lk = key.lower()
            if lk in arts:
                a = arts[lk]
                if a["kind"] == "place" and kind == "place":
                    for k in ("hold", "place_kind"):
                        if not a["info"].get(k) and info.get(k):
                            a["info"][k] = info[k]
                if a["kind"] == kind and a["src"] != src:
                    a.setdefault("extra", []).append(d["text"])
                continue
            arts[lk] = {"title": key, "src": src, "kind": kind, "info": info, "text": d["text"]}
    return arts


def build_db(arts, redirects, db_path, places_path=None):
    if os.path.exists(db_path):
        os.remove(db_path)
    con = sqlite3.connect(db_path)
    con.executescript("""
        CREATE TABLE articles(id INTEGER PRIMARY KEY, title TEXT NOT NULL, key TEXT UNIQUE,
            src TEXT, kind TEXT, place_kind TEXT, hold TEXT, town TEXT, topic TEXT);
        CREATE TABLE facts(id INTEGER PRIMARY KEY, article INTEGER NOT NULL, seq INTEGER,
            section TEXT, place TEXT, npc TEXT, topic TEXT, era TEXT, depth INTEGER,
            inside INTEGER, secret TEXT, tokens INTEGER, text TEXT NOT NULL);
        CREATE TABLE names(name TEXT PRIMARY KEY, article INTEGER NOT NULL);
        CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT);
        CREATE VIRTUAL TABLE facts_fts USING fts5(text, content='facts', content_rowid='id',
            tokenize='porter unicode61');
    """)
    places = {}
    total = 0
    aid_by_key = {}
    for lk in sorted(arts):
        a = arts[lk]
        info = a["info"]
        plain = strip_markup(a["text"])
        facts = page_facts(a["kind"], info, plain, a["title"])
        seen, uniq = [], []
        for f in facts:
            w = _words(f[3])
            if any(len(w & s2) >= 0.6 * max(1, len(w)) for s2 in seen):
                continue
            seen.append(w)
            uniq.append(f)
        facts = uniq
        for extra in a.get("extra", []):
            for f in page_facts(a["kind"], {k: v for k, v in info.items() if k != "description"},
                                strip_markup(extra)):
                if f[1] > 3:
                    continue  # second source only adds public facts
                w = _words(f[3])
                if any(len(w & s2) >= 0.6 * max(1, len(w)) for s2 in seen):
                    continue
                seen.append(w)
                facts.append(f)
        if not facts:
            continue
        facts.sort(key=lambda f: f[1])  # stable: depth first, page order within depth
        cap = ARTICLE_CAPS.get(a["kind"], 300)
        kept, used = [], 0
        for f in facts:
            t = tokens(f[3])
            if used + t > cap:
                continue
            kept.append(f)
            used += t
        topic = TOPIC_IDS.get(lk) if a["kind"] == "topic" else None
        cur = con.execute(
            "INSERT INTO articles(title,key,src,kind,place_kind,hold,town,topic) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (a["title"], lk, a["src"], a["kind"], info.get("place_kind"), info.get("hold"),
             info.get("town"), topic))
        aid = cur.lastrowid
        aid_by_key[lk] = aid
        for seq, (sec, depth, inside, text) in enumerate(kept):
            con.execute(
                "INSERT INTO facts(article,seq,section,place,npc,topic,era,depth,inside,secret,"
                "tokens,text) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (aid, seq, sec, a["title"] if a["kind"] == "place" else None,
                 a["title"] if a["kind"] == "npc" else None,
                 topic or (a["title"] if a["kind"] in ("topic", "creature") else None),
                 tag_era(text, info), depth, inside, tag_secret(text), tokens(text), text))
            total += tokens(text)
        if a["kind"] == "place":
            places[a["title"]] = {k: v for k, v in (("hold", info.get("hold")),
                                                    ("kind", info.get("place_kind")),
                                                    ("town", info.get("town"))) if v}
    # names: titles, redirects and unique NPC first names
    names = {}
    text_by_aid = {aid_by_key[lk]: arts[lk]["text"] for lk in aid_by_key}

    def proper_noun(word, aid):
        """A one-word name triggers only if its own article writes it capitalised."""
        text = text_by_aid.get(aid, "")
        low = len(re.findall(r"\b" + re.escape(word) + r"\b", text))
        cap = len(re.findall(r"\b" + re.escape(word.capitalize()) + r"\b", text))
        return low * 3 <= cap

    def add_name(n, aid):
        n = re.sub(r"\s+", " ", n.strip().lower())
        if len(n) < 4 or n in COMMON_WORDS:
            return
        if " " not in n and (not n.isalpha() or not proper_noun(n, aid)):
            return
        names.setdefault(n, aid)

    for lk, aid in aid_by_key.items():
        add_name(lk, aid)
        if lk.startswith("the "):
            add_name(lk[4:], aid)
    for src_t, tgt in redirects.items():
        aid = aid_by_key.get(title_key(tgt).lower())
        if aid:
            add_name(title_key(src_t), aid)
    firsts = {}
    for lk, a in arts.items():
        if a["kind"] == "npc" and lk in aid_by_key and " " in lk:
            firsts.setdefault(lk.split()[0], []).append(aid_by_key[lk])
    for first, ids in firsts.items():
        if len(ids) == 1:
            add_name(first, ids[0])
    con.executemany("INSERT INTO names(name,article) VALUES(?,?)", sorted(names.items()))
    con.execute("INSERT INTO facts_fts(facts_fts) VALUES('rebuild')")
    con.execute("CREATE INDEX facts_article ON facts(article, depth, seq)")
    con.executemany("INSERT INTO meta(k,v) VALUES(?,?)", [
        ("tokens", str(total)), ("articles", str(len(aid_by_key))),
        ("version", "1")])
    con.commit()
    con.execute("VACUUM")
    con.close()
    if places_path:
        with open(places_path, "w", encoding="utf-8") as f:
            json.dump(dict(sorted(places.items())), f, ensure_ascii=False, indent=0,
                      sort_keys=True)
    return total, len(aid_by_key)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--uesp")
    ap.add_argument("--fandom")
    ap.add_argument("--work", default=os.path.join(ROOT, "work"))
    ap.add_argument("--from-work", action="store_true")
    ap.add_argument("--db", default=os.path.join(ROOT, "data", "lore.sqlite"))
    ap.add_argument("--places", default=os.path.join(ROOT, "data", "places.json"))
    args = ap.parse_args(argv)
    os.makedirs(args.work, exist_ok=True)
    pages, redirects = {}, {}
    for src, dump in (("uesp", args.uesp), ("fandom", args.fandom)):
        wp = os.path.join(args.work, src + ".jsonl.gz")
        if not args.from_work and dump:
            print(src, wikidump.extract(dump, src, wp), "pages extracted")
        if os.path.exists(wp):
            pages[src], r = load_work(wp)
            redirects.update(r)
    if not pages:
        ap.error("no dumps given and no work files found")
    arts = collect(pages)
    total, n = build_db(arts, redirects, args.db, args.places)
    print(f"{n} articles, {total} tokens -> {args.db}")


if __name__ == "__main__":
    main()
