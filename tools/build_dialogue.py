"""Collect each profiled NPC's own in-game dialogue from both wiki dumps (UESP and Fandom), for writing the NPC's
"what I know" block. Also writes data/quest_ids.json (quest title -> editor ID, from UESP quest pages).

Output: work/dialogue.jsonl.gz, one JSON line per NPC with dialogue: {name, base_id, uesp, fandom, quests}, where
uesp/fandom are cleaned dialogue sections (conditions kept, e.g. "(Before you start The Golden Claw)") and quests
lists the quest titles named in them that have an editor ID.

usage: python tools/build_dialogue.py        (needs work/uesp.jsonl.gz and work/fandom.jsonl.gz from build_lore.py)
Only stdlib."""
import gzip
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, 'work')
DIALOGUE_SECTIONS = re.compile(r'^(quest-related dialogue|quest-related events|dialogue|conversations|quotes|interactions|'
                               r'related quests)$', re.I)
MAX_CHARS = 12000  # per wiki per NPC; the longest pages (Delphine, Esbern) are mostly quest walkthrough


def clean(text):
    """MediaWiki dialogue markup -> readable lines; keeps quotes, conditions and who says what."""
    t = re.sub(r'<ref[^>]*>.*?</ref>|<ref[^/]*/>', '', text, flags=re.S)
    t = re.sub(r'\[\[(?:File|Image):[^\]]*\]\]', '', t)
    t = re.sub(r'\[\[(?:[^|\]]*\|)?([^\]]*)\]\]', r'\1', t)
    for _ in range(3):
        t = re.sub(r'\{\{(?:[^{}|]*\|)?([^{}]*)\}\}', r'\1', t)
    t = re.sub(r'<[^>]+>', '', t)
    t = re.sub(r"'''?", '', t)
    t = re.sub(r'^\s*\{\||^\s*\|\}|^\s*\|-\s*$|^\s*!.*$', '', t, flags=re.M)
    t = re.sub(r'^\s*\|\s*', '', t, flags=re.M)
    t = re.sub(r'^\s*[;:]+\s*', '- ', t, flags=re.M)
    t = re.sub(r'(?i)^.*\b(bug|console|achievement|trophy|pc|xbox|playstation)\b.*$', '', t, flags=re.M)
    t = re.sub(r'\n{3,}', '\n\n', t)
    return t.strip()


def dialogue_part(text):
    """The dialogue-like sections of an article (any heading level), cleaned and joined."""
    out, keep = [], False
    for line in text.split('\n'):
        m = re.match(r'^(=+)\s*(.*?)\s*=+\s*$', line)
        if m:
            name = re.sub(r'\[\[(?:[^|\]]*\|)?([^\]]*)\]\]', r'\1', m.group(2)).strip()
            level = len(m.group(1))
            if level <= 2:
                keep = bool(DIALOGUE_SECTIONS.match(name))
            out.append(f'== {name} ==' if keep else '')
            continue
        if keep:
            out.append(line)
    return clean('\n'.join(out))


def article_key(title):
    return re.sub(r'\s*\((skyrim|npc)\)$', '', title.split(':', 1)[-1].strip().lower())


def main():
    profiles = json.load(open(os.path.join(ROOT, 'data', 'profiles.json'), encoding='utf-8'))['profiles']
    by_name = {}
    for key, p in profiles.items():
        if isinstance(p, dict) and p.get('name'):
            by_name.setdefault(p['name'].lower(), []).append(p)
    quest_ids, texts = {}, {}
    for src in ('uesp', 'fandom'):
        with gzip.open(os.path.join(WORK, f'{src}.jsonl.gz'), 'rt', encoding='utf-8') as f:
            for line in f:
                d = json.loads(line)
                title, text = d.get('title', ''), d.get('text') or ''
                if not text:
                    continue
                if src == 'uesp':
                    m = re.search(r'\|\s*ID\s*=\s*([A-Za-z0-9_]+)', text[:3000])
                    if m and re.search(r'Quest Header|\|\s*Giver', text[:3000], re.I):
                        quest_ids[title.split(':', 1)[-1].strip()] = m.group(1)
                key = article_key(title)
                if key in by_name:
                    part = dialogue_part(text)
                    if len(part) > 80:
                        texts.setdefault(key, {})[src] = part[:MAX_CHARS]
    titles = sorted(quest_ids, key=len, reverse=True)
    os.makedirs(WORK, exist_ok=True)
    n = 0
    with gzip.open(os.path.join(WORK, 'dialogue.jsonl.gz'), 'wt', encoding='utf-8') as out:
        for key, parts in sorted(texts.items()):
            joined = (parts.get('uesp', '') + '\n' + parts.get('fandom', ''))
            quests = sorted({t for t in titles if t in joined})
            for p in by_name[key]:
                out.write(json.dumps({'name': p['name'], 'base_id': p.get('base_id', ''), 'uesp': parts.get('uesp', ''),
                                      'fandom': parts.get('fandom', ''), 'quests': {t: quest_ids[t] for t in quests}},
                                     ensure_ascii=False) + '\n')
                n += 1
    with open(os.path.join(ROOT, 'data', 'quest_ids.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(dict(sorted(quest_ids.items())), f, indent=0, ensure_ascii=False)
    print(f'{n} NPC rows with dialogue ({len(texts)} names), {len(quest_ids)} quest ids')


if __name__ == '__main__':
    main()
