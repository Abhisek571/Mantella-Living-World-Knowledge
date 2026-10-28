"""Who has heard that the player is Dragonborn, from the main quest (World's quest_state):
- before Dragon Rising (MQ104) is done: nobody;
- after it: Whiterun Hold and well-travelled folk know the player killed a dragon and took its soul; elsewhere only
  rumours of a Dragonborn in Whiterun Hold;
- once the Greybeards' summons has thundered across Skyrim (MQ105 running or done): everyone has heard a Dragonborn
  exists; the player's name only where the dragon news reached (as above).
keep_secret (the player's choice in the Living World tab): nobody connects it to the player."""

QUESTS = ('MQ104', 'MQ105')


def line(quest_states, listener, player, keep_secret=False):
    states = quest_states if isinstance(quest_states, dict) else {}
    if states.get('MQ104') != 2:
        return ''
    profile = listener if isinstance(listener, dict) else {}
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
