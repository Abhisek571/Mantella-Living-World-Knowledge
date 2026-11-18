# Changelog

Every change to Mantella Living World - Knowledge. The Nexus page lists only the main changes for each version.

## Unreleased

### New
- World knowledge: facts bigger than one NPC that only some NPCs know, in knowledge packs (JSON files that mods can ship). Conditions: location, hold, faction, named group, quest stage, global, joined with and/or/not. Mode "always" or "relevant" (only when the talk touches it).
- World Knowledge page: turn packs and single facts on and off, write your own packs, edit named groups, import and export packs, set the budget. With the Integration Hub 1.2.3 or newer it is a page inside the Living World tab; with an older Hub it is a tab of its own.
- The plugin reads factions by form id, quest stages and globals for world knowledge when an NPC joins a talk.

### Changed
- Shorter description for MarkOnMap.
- knowledge_checked.json keeps only the faction lists of NPCs in the current talk instead of every NPC ever met.

### Fixed
- A world knowledge fact under a "not" condition is no longer given to everyone before the game has checked them.
- An NPC who shares a name with another NPC but has a different base record no longer gets that NPC's knowledge or secret.
- A secret is marked as never said in front of others whenever the talk has more than one speaker, also at a group talk's first request.
- Lore lines that repeat an NPC's own knowledge are no longer sent on the first reply of a talk.
- MarkOnMap: an NPC only marks places in their own hold or a neighbouring one (where they live or where they are), plus the cities and towns everyone knows; Solstheim places only from Solstheim. Before, anyone could mark any place in Skyrim.
- The game's own files (conversation and NPC files) are read without regard to the case of their keys, as the Integration Hub does. A key the game wrote as "Name" or "Player" instead of "name" or "player" no longer leaves an NPC without their knowledge profile.
- A mod NPC who shares a name with a vanilla NPC (a second "Astrid") no longer gets the vanilla NPC's profile, knowledge or secret.
- NPCs from light plugins and NPCs whose base id starts with zeros now get their knowledge profile.
- In a group talk each NPC gets their own lore lines; the second speaker no longer gets only what the first one left over.
- At the start of a talk, the NPCs Mantella is answering for are used, not the speakers of the last talk.
- Names said with 's ("Ulfric's") now bring up lore about that name.
- Names with an apostrophe or hyphen (Ri'saad, Brand-Shei, Gray-Mane, J'zargo) now bring up lore, also when written without it ("Risaad", "Gray Mane").
- Lore now loads when the mod folder path contains a #.
- Everyday words such as "goat", "first", "master" or "soldier" no longer bring up lore about a wiki page of that name.
- An NPC from a light plugin whose id ends like a vanilla NPC's no longer gets that NPC's profile, knowledge or secret.

## 1.1.0 (2026-11-09)

### New
- Secrets: NPCs can know things that are not common knowledge, and knowledge tied to quests counts too.
- Observation data for every NPC, which World uses to tell whether an NPC would recognise you.
- Mark on map: hidden places (Sky Haven Temple, the Sanctuaries, Castle Volkihar, Nightingale Hall and others) are only marked once their quest has started, and each NPC marks one place a day.

### Fixed
- Lore topics, hidden entries and who-knows-whom fixes.

## 1.0.0 (2026-10-30)
- First release. Requires Mantella Living World - Integration Hub.
