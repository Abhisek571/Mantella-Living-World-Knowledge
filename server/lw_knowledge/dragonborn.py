"""Who has heard that the player is Dragonborn, from the main quest (World's quest_state):
- before Dragon Rising (MQ104) is done: nobody;
- after it: Whiterun Hold and well-travelled folk know the player killed a dragon and took its soul; elsewhere only
  rumours of a Dragonborn in Whiterun Hold;
- once the Greybeards' summons has thundered across Skyrim (MQ105 running or done): everyone has heard a Dragonborn
  exists; the player's name only where the dragon news reached (as above).
keep_secret (the player's choice in the Living World tab): nobody connects it to the player.
Those who deal with the player as the Dragonborn in the main quest (KNOWS_PLAYER) know it from that point on, whatever
keep_secret says."""

# name -> (quest, lowest state from which they know the player as the Dragonborn)
KNOWS_PLAYER = {'Arngeir': ('MQ105', 1), 'Borri': ('MQ105', 1), 'Einarth': ('MQ105', 1), 'Wulfgar': ('MQ105', 1),
                'Delphine': ('MQ106', 1), 'Esbern': ('MQ203', 1), 'Paarthurnax': ('MQ204', 1), 'Odahviing': ('MQ303', 1)}
QUESTS = ('MQ104', 'MQ105') + tuple(sorted({q for q, _ in KNOWS_PLAYER.values()} - {'MQ105'}))


def line(quest_states, listener, player, keep_secret=False):
    states = quest_states if isinstance(quest_states, dict) else {}
    if states.get('MQ104') != 2:
        return ''
    profile = listener if isinstance(listener, dict) else {}
    name = profile.get('name') or ''
    if name in KNOWS_PLAYER:
        quest, lowest = KNOWS_PLAYER[name]
        if isinstance(states.get(quest), int) and states[quest] >= lowest:
            return f"{player} is the Dragonborn; {name} knows them as such."
    near = (profile.get('hold') or '') == 'Whiterun Hold' or profile.get('travel') == 'province'
    summoned = states.get('MQ105', 0) >= 1
    if near and not keep_secret:
        text = f"Word has it {player} killed a dragon near Whiterun and took its soul: a Dragonborn, like in the old tales."
        if summoned:
            text += " The Greybeards' summons that shook the sky was for them."
        return text
    if summoned:
        return "Everyone heard the Greybeards' summons thunder across Skyrim: a Dragonborn has come, though few know who."
    return "There are rumours that a Dragonborn killed a dragon in Whiterun Hold."
