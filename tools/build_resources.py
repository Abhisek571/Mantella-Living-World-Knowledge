"""Which mines yield which ore, from the lore database (mine articles whose facts name an ore or its veins), for gather
hints: a smith who posted an ore job on the Missives board knows a mine for it. Writes data/resources.json:
{ore: [{"mine", "hold"}, ...]}.

usage: python tools/build_resources.py        Only stdlib."""
import json
import os
import re
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORES = ['Iron Ore', 'Corundum Ore', 'Ebony Ore', 'Gold Ore', 'Malachite Ore', 'Moonstone Ore', 'Orichalcum Ore',
        'Quicksilver Ore', 'Silver Ore']


def build(db_path):
    con = sqlite3.connect(db_path)
    out = {o: [] for o in ORES}
    rows = con.execute("SELECT id, title, hold, place_kind FROM articles WHERE kind='place' AND place_kind IN ('mine', 'camp')")
    for aid, title, hold, kind in rows.fetchall():
        text = ' '.join(t for (t,) in con.execute("SELECT text FROM facts WHERE article=? AND inside=0 OR article=? AND depth<=3", (aid, aid)))
        if kind == 'camp' and not re.search(r'\bmin(e|es|ing)\b', text, re.I):
            continue  # a camp counts only when its own text says people mine there
        for ore in ORES:
            word = ore.split()[0]
            if re.search(rf'\b{word}\b[^.]*\b(ore|veins?)\b', text, re.I):
                out[ore].append({'mine': title, 'hold': hold or ''})
    con.close()
    return {o: sorted(v, key=lambda m: m['mine']) for o, v in out.items() if v}


if __name__ == '__main__':
    data = build(os.path.join(ROOT, 'data', 'lore.sqlite'))
    with open(os.path.join(ROOT, 'data', 'resources.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    print({o: len(v) for o, v in data.items()})
