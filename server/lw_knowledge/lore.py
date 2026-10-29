"""Lore lookup: names in the latest lines -> a few short facts this NPC would know.

lookup(text, npc_profile, budget) returns at most `budget` tokens of fact lines.
Nothing is returned (and the database is not queried) unless a known name
appears in the text. Facts are filtered per NPC: depth <= the NPC's level for
that place/person/topic, inside facts only at level 5, secrets only through
knows_secret, recent (4E) facts never for ancient NPCs.

Uses only sqlite3 features available in SQLite 3.38 (FTS5, no JSON functions).
"""
import os
import re
import sqlite3
import threading

from . import knowledge as K

MAX_ARTICLES = 3
_WORD_RE = re.compile(r"[a-z0-9'\-]+")
_STOP = {"the", "a", "an", "of", "and", "or", "to", "in", "on", "at", "is", "are", "was",
         "it", "you", "i", "me", "my", "we", "do", "did", "what", "who", "where", "how",
         "about", "know", "tell", "there", "that", "this", "with", "for", "have", "has"}


def default_db_path():
    return os.path.join(K.data_dir(), "lore.sqlite")


class LoreDB:
    def __init__(self, path):
        self.path = path
        self.queries = 0
        uri = "file:" + path.replace("\\", "/") + "?mode=ro"
        self.con = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self.lock = threading.Lock()
        self.names = dict(self.con.execute("SELECT name, article FROM names"))
        self.max_words = max((n.count(" ") + 1 for n in self.names), default=1)
        self.articles = {}
        for row in self.con.execute(
                "SELECT id, title, kind, place_kind, hold, town, topic FROM articles"):
            self.articles[row[0]] = {"title": row[1], "kind": row[2], "place_kind": row[3],
                                     "hold": row[4], "town": row[5], "topic": row[6]}

    def find_articles(self, text):
        """Article ids named in text, in order of first mention, longest match first."""
        words = _WORD_RE.findall((text or "").lower())
        found, i = [], 0
        while i < len(words):
            hit = None
            for n in range(min(self.max_words, len(words) - i), 0, -1):
                aid = self.names.get(" ".join(words[i:i + n]))
                if aid is not None:
                    hit = (aid, n)
                    break
            if hit:
                if hit[0] not in found:
                    found.append(hit[0])
                i += hit[1]
            else:
                i += 1
        return found

    def facts(self, article_ids, query_words):
        """Rows (id, article, depth, inside, secret, era, tokens, text, rank)."""
        self.queries += 1
        marks = ",".join("?" * len(article_ids))
        with self.lock:
            rows = self.con.execute(
                "SELECT id, article, depth, inside, secret, era, tokens, text, seq FROM facts "
                f"WHERE article IN ({marks}) ORDER BY article, depth, seq",
                list(article_ids)).fetchall()
            ranks = {}
            if query_words and rows:
                q = " OR ".join('"%s"' % w.replace('"', "") for w in query_words[:12])
                try:
                    ids = [r[0] for r in rows]
                    for rid, score in self.con.execute(
                            "SELECT rowid, bm25(facts_fts) FROM facts_fts WHERE facts_fts "
                            f"MATCH ? AND rowid IN ({','.join('?' * len(ids))})", [q] + ids):
                        ranks[rid] = score
                except sqlite3.Error:
                    ranks = {}
        return [r[:8] + (ranks.get(r[0], 0.0),) for r in rows]


_DB = None
_DB_LOCK = threading.Lock()


def get_db(path=None):
    global _DB
    path = path or default_db_path()
    with _DB_LOCK:
        if _DB is None or _DB.path != path:
            if _DB is not None:
                _DB.con.close()
            _DB = LoreDB(path) if os.path.exists(path) else None
    return _DB


def _article_level(profile, art):
    kind = art["kind"]
    if kind == "place":
        return K.place_level(profile, {"name": art["title"], "hold": art["hold"],
                                       "kind": art["place_kind"], "town": art["town"]})
    if kind == "npc":
        name = (profile.get("name") or "").lower()
        if name and name == art["title"].lower():
            return 5
        tie = {t.get("npc", "").lower(): t for t in profile.get("ties") or []
               if isinstance(t, dict) and isinstance(t.get("npc"), str)}.get(art["title"].lower())
        if tie:
            return K._tie_level(tie)
        if art["town"]:
            return min(K.place_level(profile, art["town"]), 4)
        return 2
    if kind == "topic" and art["topic"]:
        return K.topic_level(profile, art["topic"])
    if kind == "creature":
        return max(2, K.topic_level(profile, "monsters"))
    edu = profile.get("education") if isinstance(profile.get("education"), int) else 2
    return 3 if edu >= 4 else 2


# Places almost nobody has been inside. Everyone gets one rumor line at most, never wiki facts (enemy lists, layout,
# loot, puzzles); what is really there comes only from a secret the NPC is in on.
DANGEROUS = {"dungeon", "cave", "fort", "nest", "camp", "giant_camp", "shipwreck", "tower"}
RUMORS = {
    "nordic": "{t} is an old Nordic tomb {w}. Folk say the dead do not rest there, and sensible people keep away.",
    "dwemer": "{t} is an old Dwarven ruin {w}. People say few who go in ever come back.",
    "dungeon": "{t} is an old ruin {w} that people say is best left alone.",
    "cave": "{t} is a cave {w}. Travellers say outlaws or beasts lair there and give it a wide berth.",
    "fort": "{t} is an old fort {w}. Word is that outlaws or worse hold it now.",
    "camp": "{t} is a camp {w} that travellers say is best avoided.",
    "giant_camp": "Giants camp at {t} {w}, and folk keep their herds well away.",
    "nest": "Folk say something dangerous has made its lair at {t} {w}.",
    "shipwreck": "{t} is a wreck {w}, and sailors call it bad luck to go near.",
    "tower": "{t} is an old ruined tower {w} that locals keep away from.",
}
RUMOR_DEPTH = 2
_WHERE_RE = re.compile(r"\b((?:north|south|east|west)[a-z-]* of|above|below|near|outside|in) "
                       r"((?:the )?[A-Z][\w']*(?: [A-Z][\w']*)*)")


def rumor(art, lead):
    """The one line people tell each other about a dangerous place: what it is and where, from the wiki lead."""
    where = ""
    for m in _WHERE_RE.finditer(lead or ""):
        if m.group(2) not in ("Skyrim", art["title"]):
            where = f"{m.group(1)} {m.group(2)}"
            break
    if not where and art.get("hold"):
        where = f"in {art['hold']}"
    kind = art.get("place_kind")
    if kind == "dungeon":
        low = (lead or "").lower()
        kind = "dwemer" if ("dwemer" in low or "dwarven" in low) else "nordic" if re.search(r"nord|tomb|barrow", low) else "dungeon"
    return re.sub(r"\s+([.,])", r"\1", re.sub(r" {2,}", " ", RUMORS[kind].format(t=art["title"], w=where)))


def place_secrets(title, name, world):
    """(id, text) of secrets about this place that the NPC is in on (secrets.json "places")."""
    out = []
    for sid, s in K.secrets().items():
        if title.lower() in {p.lower() for p in s.get("places") or []} and K.knows_secret(name, s, world):
            out += [(f"secret:{sid}:{i}", t) for i, t in enumerate(s.get("text_pieces") or [])]
    return out


# Game-guide wording: what a player reads in a guide, never what people in the world know.
_GUIDE_RE = re.compile(r"\b(can be found|is found|are found|is located|located (?:in|at|near)|the (?:last )?dragonborn|the player|"
                       # a guide's view of the story: who the player fights in the end
                       r"(?:main|primary|supporting) antagonist|"
                       r"you can|quest|walkthrough|tutorial|console|wears?\b|wearing|carries|equipped|spells?\b|"
                       r"\d{1,2}\s?(?:am|pm)\b|schedule|sells?\b|buy|merchant|gold\b|septims?\b|level \d|in skyrim|dragon language|initially|depending on|if you|once you|after you|"
                       # room inventories and loot: what a guide lists, not what anyone talks about
                       r"owned (?:single |double )?beds?|common books?|loose (?:gold|coins?)|bottles? of|potions? of|dresser|end table|"
                       r"night ?stand|wardrobe|cupboard|satchel|knapsack|leveled|randomly|random (?:items?|loot)|(?:un)?locked chest|"
                       r"(?:novice|apprentice|adept|expert|master)-locked|skill books?|(?:reading|in) (?:his|her|their|the) (?:journal|diary|note)|"
                       r"research notes|can be (?:picked|looted|taken)|respawn)", re.I)


def is_guide_text(sentence):
    return bool(_GUIDE_RE.search(sentence or ""))


# People: one who-and-where line, never the wiki's narration. Who has heard of whom: rulers everywhere, high-standing
# people (court, guild heads) in their hold or by well-travelled folk, everyone else only in their own town.
# Outlaws and monsters by nobody.
_HIDDEN_JOBS = {"bandit", "thief", "necromancer", "vampire", "creature", "assassin", "cultist", "forsworn", "warlock"}
# Minor places: one what-and-where line, known in their hold.
MINOR = {"house", "store", "inn", "farm", "mine", "shack", "building", "dock", "guild", "temple", "shrine", "palace",
         "military", "camp_military", "grove", "ship", "monastery"}
_KIND_WORD = {"store": "shop", "camp_military": "army camp", "military": "military post", "guild": "guild hall"}
MINOR_TIED_LEVEL = 4  # a tie or the own town: known from outside even in another hold (Ivarstead and High Hrothgar)


def people_line(title, listener):
    who = K.profile_for(title) or {}
    if not who:
        return None
    job = (who.get("profession") or "").replace("_", " ")
    home, hold = who.get("home") or "", who.get("hold") or ""
    tied = any(isinstance(t, dict) and (t.get("npc") or "").lower() == title.lower() for t in listener.get("ties") or [])
    if who.get("profession") in _HIDDEN_JOBS and not tied:
        return None
    standing = who.get("standing")
    same_town = home and home.lower() == (listener.get("home") or "").lower()
    same_hold = hold and hold.lower() == (listener.get("hold") or "").lower()
    known = tied or standing == "ruler" or same_town or (standing == "high" and (same_hold or listener.get("travel") == "province"))
    if not known or not home:
        return None
    if standing == "ruler" and hold:
        return f"{title} rules {hold} from {home}."
    job = {"": "local", "commoner": "local", "court": "member of the court"}.get(job, job)
    where = home if same_hold else f"{home}, {hold}" if hold else home
    return f"{title} is {'an' if job[0] in 'aeiou' else 'a'} {job} in {where}."


def minor_line(art, listener, level=0):
    hold = art.get("hold") or ""
    if not hold or (hold.lower() != (listener.get("hold") or "").lower() and level < MINOR_TIED_LEVEL):
        return None
    kind = _KIND_WORD.get(art.get("place_kind"), art.get("place_kind") or "place").replace("_", " ")
    where = art.get("town") or hold
    return f"{art['title']} is {'an' if kind[0] in 'aeiou' else 'a'} {kind} in {where}."


def lookup(text, npc_profile, budget=150, world=None, sent=None, db_path=None):
    """Lore lines for this NPC about names mentioned in text, within budget tokens.

    sent: optional set of fact ids already given this conversation; updated in place.
    Never raises: any error returns []."""
    try:
        if not text or budget <= 0:
            return []
        db = get_db(db_path)
        if db is None:
            return []
        profile = npc_profile if isinstance(npc_profile, dict) else {}
        home = (profile.get("home") or "").lower()
        # Their own home needs no lore: they live there, and the scene already names it.
        arts = [a for a in db.find_articles(text) if not (home and db.articles[a]["kind"] == "place"
                                                          and db.articles[a]["title"].lower() == home)][:MAX_ARTICLES]
        if not arts:
            return []
        levels = {a: _article_level(profile, db.articles[a]) for a in arts}
        words = [w for w in _WORD_RE.findall(text.lower()) if w not in _STOP and len(w) > 2]
        ancient = profile.get("era") == "ancient"
        name = profile.get("name")
        dangerous = {a for a in arts if db.articles[a]["kind"] == "place" and db.articles[a]["place_kind"] in DANGEROUS}
        # People and minor places get one generated line instead of their wiki facts.
        generated = {}
        for a in arts:
            art = db.articles[a]
            if art["kind"] == "npc":
                generated[a] = people_line(art["title"], profile)
            elif art["kind"] == "place" and art["place_kind"] in MINOR:
                generated[a] = minor_line(art, profile, levels[a])
        leads = {}
        cands = []
        for fid, aid, depth, inside, secret, era, ntok, ftext, rank in db.facts(arts, words):
            lvl = levels[aid]
            if aid in dangerous:
                if not inside and (aid not in leads or depth < leads[aid][0]):
                    leads[aid] = (depth, ftext)
                continue
            if aid in generated and not secret:
                continue
            if not secret and is_guide_text(ftext):
                continue
            if secret:
                # Secrets ignore levels both ways: only those in on it, and they know it fully.
                if not K.knows_secret(name, secret, world):
                    continue
            elif depth > lvl or (inside and lvl < 5):
                continue
            if ancient and era == "4E":
                continue
            if sent is not None and fid in sent:
                continue
            cands.append((arts.index(aid), depth, rank, str(fid), fid, ntok, ftext))
        for aid, line in generated.items():
            if line and (sent is None or f"who:{aid}" not in sent):
                cands.append((arts.index(aid), 0, 0.0, f"who:{aid}", f"who:{aid}", (len(line) + 3) // 4, line))
        for aid in dangerous:
            art = db.articles[aid]
            lines = place_secrets(art["title"], name, world)
            if levels[aid] >= RUMOR_DEPTH:
                lines.insert(0, (f"rumor:{aid}", rumor(art, leads.get(aid, (0, ""))[1])))
            for depth, (fid, ftext) in enumerate(lines):
                if sent is None or fid not in sent:
                    cands.append((arts.index(aid), depth, 0.0, fid, fid, (len(ftext) + 3) // 4, ftext))
        cands.sort(key=lambda c: c[:4])
        out, used = [], 0
        for _, _, _, _, fid, ntok, ftext in cands:
            if used + ntok > budget:
                continue
            out.append(ftext)
            used += ntok
            if sent is not None:
                sent.add(fid)
        return out
    except Exception:  # noqa: BLE001 - lore is optional, never break the reply
        return []
