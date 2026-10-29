# Mantella Living World - Knowledge

Each NPC knows what fits their life, and no more. An optional module of [Mantella Living World - Integration Hub](https://github.com/Abhisek571/Mantella-Living-World-Hub).

| Feature | What it does |
|---|---|
| Knowledge levels | Home, hold, origin, profession, travel and personal ties set a level from 1 to 5 for each place and topic. Levels only decide which lore facts an NPC is handed |
| What each NPC knows | Each NPC gets a short "what they know" block built from their own dialogue. Lines tied to a quest only show once that quest has reached the stage |
| Identity line | One line per NPC: job, home, hold, province, and whether they rarely leave or travel around. It also lists places they have never been inside |
| Secrets | Quest secrets sit above level 5. They unlock through quest progress, or because the NPC was in on it from the start. There is no way to "tell" an NPC a secret |
| Dragonborn rumours | Who has heard the player is Dragonborn depends on the main quest and on where the NPC lives or travels. Needs the World module |
| Common knowledge | One block everyone knows, the same for every NPC so it caches |
| Lore lookups | Short facts from a lore database about names the player mentions, within a token budget, filtered by the NPC's levels. Room contents and loot lists are never sent. Dangerous places only get a short rumour |
| Mark on map | The MarkOnMap action puts a place the NPC knows on the player's map when asked the way. It does not fast travel |

| Level | Meaning |
|---|---|
| 1 | Heard of it |
| 2 | Knows where it is and what people say |
| 3 | Knows it like a local of the hold |
| 4 | Knows it well (own town, a personal tie) |
| 5 | Has been inside / knows it first hand |

Rules: own town 4, own hold 3, neighbouring hold 2, far 1; profession bonus +1 (merchants on trade towns, soldiers on forts, priests on temples, hunters in the wilds, guards in their hold); origin province 3; travellers +1 on their routes; couriers 3 on every road and town; ties override; 5 only with `inside`; ancient NPCs never know recent events. Hand ratings in `data/ratings/batch_*.json` override the rule values.

Limits: profiles cover about 3,100 vanilla NPCs only. An NPC whose name matches more than one profile and has no matching base id gets none. Modded NPCs get no Knowledge block. In group talks the lore budget is shared between the NPCs and at most 3 named articles are used per reply. Knowledge removes lines from an NPC's bio that describe quest stages ("If...", "Once...", "After..."), so they do not contradict the knowledge block. Mantella's own files are not changed.

Settings: the Hub's "Knowledge mode" is off, profiles only, or profiles and lore. The Hub's Status tab warns when the lore database is missing.

Requires:
- [Mantella Living World - Integration Hub](https://github.com/Abhisek571/Mantella-Living-World-Hub), [Mantella](https://www.nexusmods.com/skyrimspecialedition/mods/98631) 0.14 and [Mantella - Direct AI Connect](https://github.com/Abhisek571/Mantella-Anthropic-API).
- SKSE and PapyrusUtil (for the map markers). SKSE_HTTP comes with Mantella.
- Mantella must run with `SKSE/Plugins/MantellaSoftware` as its working folder. Under Mod Organizer 2 it must be started so it can see the game's `StorageUtilData/MantellaLivingWorld` files.
- Mantella's Advanced Actions on (Actions tab of Mantella's settings) for MarkOnMap.

Optional:
- Mantella Living World - World: needed for everything tied to a quest (quest-gated knowledge lines, quest secrets, Dragonborn rumours). Without it only untied lines, "in on it" secrets and no Dragonborn rumours.
- Dawnguard and Dragonborn: needed for their 16 and 54 map markers.

Build: the Hub's `tools/build.py --only knowledge`. The data needs Python 3.11 (stdlib only) and 7-Zip:

```
python tools/build_lore.py --uesp uespwiki-YYYY-MM-DD-current.xml.bz2 --fandom elderscrolls_pages_current.xml.7z
python tools/build_profiles.py --csv skyrim_characters.csv
python -m unittest discover -s tests
```

`build_lore.py` keeps the Skyrim pages of both wiki dumps, strips markup and non-lore sections, merges duplicates and cuts the text into tagged facts of at most 80 tokens. Run it before `build_profiles.py`.

License: GNU AGPL-3.0 for the code. The lore database (`data/lore.sqlite`) is not in this repository; the released mod includes one built from [UESP](https://en.uesp.net) (CC BY-SA 2.5) and the [Elder Scrolls Fandom wiki](https://elderscrolls.fandom.com) (CC BY-SA 3.0) text, under those licences, with credit to their authors. The lore database is shared under those same licences.

Author: itsPigeon2000
