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

## 1.1.0 (2026-11-09)

### New
- Secrets: NPCs can know things that are not common knowledge, and knowledge tied to quests counts too.
- Observation data for every NPC, which World uses to tell whether an NPC would recognise you.
- Mark on map: hidden places (Sky Haven Temple, the Sanctuaries, Castle Volkihar, Nightingale Hall and others) are only marked once their quest has started, and each NPC marks one place a day.

### Fixed
- Lore topics, hidden entries and who-knows-whom fixes.

## 1.0.0 (2026-10-30)
- First release. Requires Mantella Living World - Integration Hub.
