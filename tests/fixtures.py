"""Small hand-written wiki pages in the dumps' markup, used to build a test lore DB."""

BARROW = """{{About|the place|the quest|Skyrim:Bleak Falls Barrow (quest)}}{{Place Summary
|type=Nordic Ruin
|region=Falkreath Hold
|location=West of [[Skyrim:Riverwood|Riverwood]]
|description=An old [[Skyrim:Nordic Ruins|Nordic ruin]] on the mountain above [[Skyrim:Riverwood|Riverwood]].
}}[[Category:Skyrim-Places-Draugr Crypts]]
Its '''ruined tower''' can be seen from the village below.<ref>Seen in game.</ref>
{| class="wikitable"
! Item !! Value
|-
| Iron Ore || 2
|}
==Background==
Ancient [[Skyrim:Nords|Nords]] buried their dead here long ago, and the locals say the dead do not rest.
==Bleak Falls Temple==
Deep inside, a gate is opened by turning three stone pillars to match the carved animal heads.
A lever beside the pillars shoots poison darts if the order is wrong.
==Bleak Falls Sanctum==
The great door at the end has three rings marked with animals and opens with the golden claw.
Behind the door a word wall stands over the coffin of a draugr overlord.
==Bugs==
* The door sometimes fails to open on the console version of the game.
"""

RIVERWOOD = """{{Place Summary
|type=Town
|region=Whiterun Hold
|description=a small lumber [[Skyrim:Towns|town]] in southern [[Skyrim:Whiterun Hold|Whiterun Hold]].
}}
Riverwood sits on the bank of the [[Skyrim:White River|White River]] below the old barrow.
The mill is run by a family whose ancestors founded the village.
==Notes==
* You can sell firewood to the mill owner.
"""

CAMILLA = """{{NPC Summary
|town=[[Skyrim:Riverwood|Riverwood]]
|race=Imperial
|baseid=0001347B
}}
'''Camilla Valerius''' is an Imperial woman who helps her brother [[Skyrim:Lucan Valerius|Lucan]] run the Riverwood Trader.
Two men of the village are fond of her.
==Dialogue==
"I came to Skyrim looking for a better life."
"""

ALDUIN = """{{Creature Summary
|race=Dragon
}}
'''Alduin''' is a huge black dragon from the old Nord legends.
The old songs say Alduin was cast out of time, and now he is raising the other dragons back to life.
"""

PAGES = {
    "uesp": [
        {"src": "uesp", "title": "Skyrim:Bleak Falls Barrow (place)", "text": BARROW},
        {"src": "uesp", "title": "Skyrim:Riverwood", "text": RIVERWOOD},
        {"src": "uesp", "title": "Skyrim:Camilla Valerius", "text": CAMILLA},
        {"src": "uesp", "title": "Skyrim:Alduin", "text": ALDUIN},
    ]
}
REDIRECTS = {"Skyrim:Bleak Falls": "Skyrim:Bleak Falls Barrow (place)"}
