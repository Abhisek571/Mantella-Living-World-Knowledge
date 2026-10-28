"""Load the NPC "what I know" blocks (work/knows_out/*.json, written to tools/knows_spec.md) into data/lore.sqlite
(table npc_knows), after checking them, and write the quest list the World module tracks for them
(SKSE/Plugins/StorageUtilData/MantellaLivingWorld/knowledge_quests.json, JsonUtil format).

usage: python tools/build_knows.py        Only stdlib."""
import glob
import json
import os
import re
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATES = {'not_started', 'running', 'done', 'not_done'}
ALWAYS_TRACKED = ('MQ104', 'MQ105')  # the Dragonborn stage (server/lw_knowledge/dragonborn.py)
MAX_ALWAYS, MAX_WHEN, MAX_WHEN_LINES, MAX_WORDS = 6, 4, 3, 35
# Words that mean the line is about the game, not the world
META = re.compile(r'\b(quest|(?<!lute )(?<!flute )(?<!drum )player|NPC|the game|XP|level up)\b', re.I)  # a lute player is fine


def tokens(text):
    return (len(text) + 3) // 4


def good_line(text, max_words=MAX_WORDS):
    return isinstance(text, str) and text.strip() and len(text.split()) <= max_words and not META.search(text)


def rows_for(block, quest_ids):
    """(rows, rejected count) for one block; a bad line or entry is dropped, the rest kept."""
    rows, rejected = [], 0
    name, base_id = block.get('name', '').strip(), (block.get('base_id') or '').upper()
    if not name:
        return [], 1
    for i, line in enumerate((block.get('always') or [])[:MAX_ALWAYS]):
        if good_line(line):
            rows.append((name.lower(), base_id, '', '', i, line.strip()))
        else:
            rejected += 1
    for j, entry in enumerate((block.get('when') or [])[:MAX_WHEN]):
        quest, state = entry.get('quest', ''), entry.get('state', '')
        if quest not in quest_ids or state not in STATES:
            rejected += 1
            continue
        for k, line in enumerate((entry.get('lines') or [])[:MAX_WHEN_LINES]):
            if good_line(line, MAX_WORDS + 15):  # stage lines carry a little more context
                rows.append((name.lower(), base_id, quest, state, 100 + j * 10 + k, line.strip()))
            else:
                rejected += 1
    secret = block.get('secret') or ''
    if secret:
        if isinstance(secret, str) and len(secret.split()) <= 40:
            rows.append((name.lower(), base_id, '', 'secret', 900, secret.strip()))
        else:
            rejected += 1
    return rows, rejected


def merge_blocks(files):
    """One block per NPC (name + base_id) from lists of blocks in file order; a later file's block replaces an earlier
    one (long_*.json redoes the NPCs whose wiki dialogue was cut off in their batch)."""
    merged = {}
    for blocks in files:
        for block in blocks:
            merged[(block.get('name', '').strip().lower(), (block.get('base_id') or '').upper())] = block
    return list(merged.values())


def load_blocks(blocks, db_path, quest_ids):
    con = sqlite3.connect(db_path)
    con.execute("DROP TABLE IF EXISTS npc_knows")
    con.execute("CREATE TABLE npc_knows (npc TEXT NOT NULL, base_id TEXT, quest TEXT, state TEXT, seq INTEGER, "
                "text TEXT NOT NULL, tokens INTEGER)")
    report = {'npcs': 0, 'rows': 0, 'rejected': 0}
    for block in blocks:
        rows, rejected = rows_for(block, quest_ids)
        report['rejected'] += rejected
        if rows:
            report['npcs'] += 1
            report['rows'] += len(rows)
            con.executemany("INSERT INTO npc_knows VALUES (?,?,?,?,?,?,?)", [r + (tokens(r[5]),) for r in rows])
    con.execute("CREATE INDEX IF NOT EXISTS npc_knows_npc ON npc_knows(npc)")
    con.commit()
    con.close()
    return report


def write_quest_list(db_path, out_path):
    con = sqlite3.connect(db_path)
    quests = sorted({q for (q,) in con.execute("SELECT DISTINCT quest FROM npc_knows WHERE quest != ''")} | set(ALWAYS_TRACKED))
    con.close()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump({'stringList': {'quests': quests}}, f, indent=1)
    return quests


def main():
    quest_ids = set(json.load(open(os.path.join(ROOT, 'data', 'quest_ids.json'), encoding='utf-8')).values())
    paths = sorted(glob.glob(os.path.join(ROOT, 'work', 'knows_out', '*.json')), key=lambda p: os.path.basename(p).startswith('long_'))
    blocks = merge_blocks(json.load(open(path, encoding='utf-8')) for path in paths)
    report = load_blocks(blocks, os.path.join(ROOT, 'data', 'lore.sqlite'), quest_ids)
    quests = write_quest_list(os.path.join(ROOT, 'data', 'lore.sqlite'),
                              os.path.join(ROOT, 'SKSE', 'Plugins', 'StorageUtilData', 'MantellaLivingWorld', 'knowledge_quests.json'))
    print(f"{report['npcs']} NPCs, {report['rows']} lines, {report['rejected']} rejected, {len(quests)} quests tracked")


if __name__ == '__main__':
    main()
