Scriptname MLWK_Map extends Quest
{Mantella Living World - Knowledge: an NPC marks a place on the player's map when asked the way (Mantella action
MarkOnMap, argument "place"). The place name is looked up in MantellaLivingWorld/markers.json (the vanilla map
markers of Skyrim.esm, Dawnguard.esm and Dragonborn.esm, by name) and shown on the map, without fast travel. A
secret place (its "gate:<name>" quest in markers.json) only once that quest has started. Each NPC marks at most one
place a day. The talk is told when nothing could be marked.}

string Property MARKERS = "MantellaLivingWorld/markers.json" AutoReadOnly
string Property ACTION_ID = "mantella_mlwk_mark_on_map" AutoReadOnly
string Property MARKED_DAY = "MLWK_MarkedDay" AutoReadOnly

Event OnInit()
	Register()
EndEvent

Function Register()
	RegisterForModEvent("MantellaConversation_Advanced_Action_" + ACTION_ID, "OnMarkOnMap")
EndFunction

Event OnMarkOnMap(Form akSpeaker, Form akConversation, int aiArguments)
	string place = SKSE_HTTP.getString(aiArguments, "place")
	Actor speaker = akSpeaker as Actor
	string who = "Someone"
	If speaker
		who = speaker.GetDisplayName()
	EndIf
	string player = Game.GetPlayer().GetDisplayName()
	int today = Utility.GetCurrentGameTime() as int
	If speaker && StorageUtil.GetIntValue(speaker, MARKED_DAY, -1) == today
		Send(who + " already marked a place on " + player + "'s map today.")
		Return
	EndIf
	string placeName = MarkerKey(Lower(place))
	If placeName == ""
		Send(who + " could not mark that place on the map.")
		Return
	EndIf
	string gate = JsonUtil.GetStringValue(MARKERS, "gate:" + placeName, "")
	If gate != ""
		Quest q = Quest.GetQuest(gate)
		If !q || q.GetStage() == 0
			Send(who + " does not know the way there.")
			Return
		EndIf
	EndIf
	If !Mark(placeName)
		Send(who + " could not mark that place on the map.")
		Return
	EndIf
	If speaker
		StorageUtil.SetIntValue(speaker, MARKED_DAY, today)
	EndIf
	Send(who + " marked " + place + " on " + player + "'s map.")
EndEvent

; The markers.json name for a place as the NPC said it: as said, without a leading "the ", or up to the first comma;
; "" when none is known.
string Function MarkerKey(string asLower)
	string placeName = Trim(asLower)
	If placeName == ""
		Return ""
	EndIf
	If JsonUtil.GetIntValue(MARKERS, placeName, 0) != 0
		Return placeName
	EndIf
	int comma = StringUtil.Find(placeName, ",")
	If comma > 0
		placeName = Trim(StringUtil.Substring(placeName, 0, comma))
	EndIf
	If StringUtil.Find(placeName, "the ") == 0 && StringUtil.GetLength(placeName) > 4
		placeName = Trim(StringUtil.Substring(placeName, 4))
	EndIf
	If placeName != "" && JsonUtil.GetIntValue(MARKERS, placeName, 0) != 0
		Return placeName
	EndIf
	Return ""
EndFunction

; Marks the place with this markers.json name; false when its marker is missing (a DLC not loaded).
bool Function Mark(string asKey)
	int id = JsonUtil.GetIntValue(MARKERS, asKey, 0)
	string plugin = JsonUtil.GetStringValue(MARKERS, asKey, "")
	If id == 0 || plugin == ""
		Return false
	EndIf
	ObjectReference marker = Game.GetFormFromFile(id, plugin) as ObjectReference
	If !marker
		Return false
	EndIf
	marker.AddToMap(false)
	Return true
EndFunction

string Function Trim(string asText)
	int n = StringUtil.GetLength(asText)
	int first = 0
	While first < n && StringUtil.GetNthChar(asText, first) == " "
		first += 1
	EndWhile
	int last = n - 1
	While last >= first && StringUtil.GetNthChar(asText, last) == " "
		last -= 1
	EndWhile
	If last < first
		Return ""
	EndIf
	Return StringUtil.Substring(asText, first, last - first + 1)
EndFunction

string Function Lower(string asText)
	string upper = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
	string lower = "abcdefghijklmnopqrstuvwxyz"
	string out = ""
	int i = 0
	int n = StringUtil.GetLength(asText)
	While i < n
		string c = StringUtil.GetNthChar(asText, i)
		int at = StringUtil.Find(upper, c)
		If at >= 0
			c = StringUtil.GetNthChar(lower, at)
		EndIf
		out += c
		i += 1
	EndWhile
	Return out
EndFunction

Function Send(string asLine)
	int handle = ModEvent.Create("MantellaAddEvent")
	If handle
		ModEvent.PushString(handle, asLine)
		ModEvent.Send(handle)
	EndIf
EndFunction
