Scriptname MLWK_PlayerAlias extends ReferenceAlias
{Player alias of the Knowledge map quest: re-registers its events on every game load.}

Event OnPlayerLoadGame()
	MLWK_Map map = GetOwningQuest() as MLWK_Map
	If map
		map.Register()
	EndIf
EndEvent
