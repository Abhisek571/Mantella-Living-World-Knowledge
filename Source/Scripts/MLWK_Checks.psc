Scriptname MLWK_Checks extends Quest
{Mantella Living World - Knowledge: the game data world knowledge conditions need and Mantella's side cannot see.
When an NPC joins a Mantella conversation it reads MantellaLivingWorld/knowledge_checks.json (written by Mantella's
side from the knowledge packs in use) and writes MantellaLivingWorld/knowledge_checked.json: each listed global's
value ("global:<key>"), each listed quest's stage and whether it is completed ("stage:<id>", "done:<id>"), and the
listed factions this NPC is in ("factions:<base id>"), with the player's name and the day.}

string Property CHECKS = "MantellaLivingWorld/knowledge_checks.json" AutoReadOnly
string Property CHECKED = "MantellaLivingWorld/knowledge_checked.json" AutoReadOnly

Event OnInit()
	Register()
EndEvent

Function Register()
	RegisterForModEvent("MantellaConversation_NPC_Added", "OnNpcAdded")
EndFunction

; The file is shared by every save and gained a faction list for every NPC ever met: only the lists of NPCs who joined
; in the last few minutes (the current talk) are kept.
Function DropOldLists(string asKeep)
	float now = Utility.GetCurrentRealTime()
	StorageUtil.SetFloatValue(None, "MLWK_ListAt_" + asKeep, now)
	string[] lists = JsonUtil.PathMembers(CHECKED, ".stringList")
	int i = 0
	While lists && i < lists.Length
		string name = lists[i]
		If StringUtil.Find(name, "factions:") == 0 && name != asKeep
			float at = StorageUtil.GetFloatValue(None, "MLWK_ListAt_" + name, -1000.0)
			If at > now || now - at > 300.0
				JsonUtil.StringListClear(CHECKED, name)
				JsonUtil.UnsetStringValue(CHECKED, name)
				StorageUtil.UnsetFloatValue(None, "MLWK_ListAt_" + name)
			EndIf
		EndIf
		i += 1
	EndWhile
EndFunction

Event OnNpcAdded(Form akActor)
	If StorageUtil.GetIntValue(None, "MLW_TimingOn", 0) == 1  ; speed testing (off by default): one stage-time row
		MiscUtil.WriteToFile("Data/SKSE/Plugins/StorageUtilData/MantellaLivingWorld/timing_game.csv", StorageUtil.GetIntValue(None, "MLW_TimingTalk", 0) + "," + Utility.GetCurrentRealTime() + ",MLWK_Checks,OnNpcAdded_start,\n", true, false)
	EndIf
	Actor npc = akActor as Actor
	Actor player = Game.GetPlayer()
	If !npc || npc == player
		Return
	EndIf
	JsonUtil.Unload(CHECKS, false)  ; Mantella's side rewrites it when packs change: read it fresh
	JsonUtil.SetStringValue(CHECKED, "player", player.GetDisplayName())
	JsonUtil.SetIntValue(CHECKED, "day", Utility.GetCurrentGameTime() as int)
	int n = JsonUtil.StringListCount(CHECKS, "global_keys")
	int i = 0
	While i < n
		string globalKey = "global:" + JsonUtil.StringListGet(CHECKS, "global_keys", i)
		GlobalVariable g = Game.GetFormFromFile(JsonUtil.IntListGet(CHECKS, "global_ids", i), JsonUtil.StringListGet(CHECKS, "global_plugins", i)) as GlobalVariable
		If g
			JsonUtil.SetFloatValue(CHECKED, globalKey, g.GetValue())
		Else
			JsonUtil.UnsetFloatValue(CHECKED, globalKey)  ; plugin not loaded: the condition counts as not met
		EndIf
		i += 1
	EndWhile
	n = JsonUtil.StringListCount(CHECKS, "quests")
	i = 0
	While i < n
		string id = JsonUtil.StringListGet(CHECKS, "quests", i)
		Quest q = Quest.GetQuest(id)
		If q
			JsonUtil.SetIntValue(CHECKED, "stage:" + id, q.GetStage())
			JsonUtil.SetIntValue(CHECKED, "done:" + id, q.IsCompleted() as int)
		Else
			JsonUtil.UnsetIntValue(CHECKED, "stage:" + id)
			JsonUtil.UnsetIntValue(CHECKED, "done:" + id)
		EndIf
		i += 1
	EndWhile
	string list = "factions:" + BaseId(npc)
	DropOldLists(list)
	JsonUtil.StringListClear(CHECKED, list)
	n = JsonUtil.StringListCount(CHECKS, "faction_keys")
	i = 0
	While i < n
		Faction f = Game.GetFormFromFile(JsonUtil.IntListGet(CHECKS, "faction_ids", i), JsonUtil.StringListGet(CHECKS, "faction_plugins", i)) as Faction
		If f && npc.IsInFaction(f)
			JsonUtil.StringListAdd(CHECKED, list, JsonUtil.StringListGet(CHECKS, "faction_keys", i), false)
		EndIf
		i += 1
	EndWhile
	JsonUtil.Save(CHECKED)
	If StorageUtil.GetIntValue(None, "MLW_TimingOn", 0) == 1  ; speed testing (off by default): one stage-time row
		MiscUtil.WriteToFile("Data/SKSE/Plugins/StorageUtilData/MantellaLivingWorld/timing_game.csv", StorageUtil.GetIntValue(None, "MLW_TimingTalk", 0) + "," + Utility.GetCurrentRealTime() + ",MLWK_Checks,OnNpcAdded_end,\n", true, false)
	EndIf
EndEvent

; The NPC's base id as the Integration Hub names their file: the last 6 hex digits of the base form id.
string Function BaseId(Actor akNpc)
	string digits = "0123456789ABCDEF"
	int value = akNpc.GetActorBase().GetFormID()
	string out = ""
	int i = 2
	While i < 8
		out += StringUtil.GetNthChar(digits, Math.LogicalAnd(Math.RightShift(value, 28 - i * 4), 15))
		i += 1
	EndWhile
	Return out
EndFunction
