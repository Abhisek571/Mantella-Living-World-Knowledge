# Mantella Living World - Knowledge

Optional add-on for Mantella Living World. Each NPC knows what fits their life: home, hold, origin, profession, travel and personal ties set a knowledge level from 1 to 5 for each place and topic. Quest secrets sit above level 5 and unlock only by quest progress or by being told. A lore database built from wiki dumps answers short lookups within a token budget.

| Part | File |
|---|---|
| NPC profiles (one per Mantella character row) | `data/profiles.json` |
| Places (hold, kind, town) | `data/places.json` |
| Secrets | `data/secrets.json` |
| Knowledge rule | `data/prompt_rules/30_knowledge.txt` |
| Common knowledge block | `data/common_knowledge.txt` |
| Lore database (built locally, not shipped in the repo) | `data/lore.sqlite` |
| Server extension (`extensions/lw_knowledge/`) | `server/lw_knowledge/` |

## Levels

| Level | Meaning |
|---|---|
| 1 | Heard of it |
| 2 | Knows where it is and what people say |
| 3 | Knows it like a local of the hold |
| 4 | Knows it well (own town, a personal tie) |
| 5 | Has been inside / knows it first hand |

Rules: own town 4, own hold 3, neighbouring hold 2, far 1; profession bonus +1 (merchants on trade towns, soldiers on forts, priests on temples, hunters in the wilds, guards in their hold); origin province 3; travellers +1 on their routes; couriers 3 on every road and town; ties override; 5 only with `inside`; ancient NPCs never know recent events.

## Build

In game it needs the Integration Hub and [Mantella - Direct AI Connect](https://github.com/Abhisek571/Mantella-Anthropic-API) (its server part runs inside it). Building the data needs Python 3.11 (stdlib only).

```
python tools/build_lore.py --uesp uespwiki-YYYY-MM-DD-current.xml.bz2 --fandom elderscrolls_pages_current.xml.7z
python tools/build_profiles.py --csv skyrim_characters.csv
python -m unittest discover -s tests
```

`build_lore.py` streams both MediaWiki dumps (7-Zip is used to read the `.7z`), keeps Skyrim pages, strips markup and non-lore sections, merges duplicate titles and cuts the text into tagged facts of at most 80 tokens. Run it before `build_profiles.py`, which reads `data/places.json` and the extracted UESP pages in `work/`.

Hand ratings for fields only a bio can decide live in `data/ratings/batch_*.json` and override the rule values.

## Licence

AGPL-3.0. Wiki text is not included; the build tool creates the database from your own copy of the dumps.
