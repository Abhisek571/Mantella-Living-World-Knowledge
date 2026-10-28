Scriptname MLWK_Map extends Quest
{Mantella Living World - Knowledge: an NPC marks a place on the player's map when asked the way (Mantella action
MarkOnMap, argument "place"). The place name is looked up in MantellaLivingWorld/markers.json (the vanilla map
markers of Skyrim.esm, Dawnguard.esm and Dragonborn.esm, by name) and shown on the map, without fast travel. At most
one place per conversation.}

string Property MARKERS = "MantellaLivingWorld/markers.json" AutoReadOnly
string Property ACTION_ID = "mantella_mlwk_mark_on_map" AutoReadOnly

bool markedThisTalk

Event OnInit()
	Register()
EndEvent

Function Register()
	RegisterForModEvent("MantellaConversation_Advanced_Action_" + ACTION_ID, "OnMarkOnMap")
	RegisterForModEvent("MantellaConversation_Started", "OnTalkStarted")
EndFunction

Event OnTalkStarted()
	markedThisTalk = false
EndEvent

Event OnMarkOnMap(Form akSpeaker, Form akConversation, int aiArguments)
	string place = SKSE_HTTP.getString(aiArguments, "place")
	string result = Mark(place)
	string who = "Someone"
	If akSpeaker
		who = (akSpeaker as Actor).GetDisplayName()
	EndIf
	If result != ""
		Send("(" + who + " marked " + result + " on " + Game.GetPlayer().GetDisplayName() + "'s map.)")
	EndIf
EndEvent

; Marks the named place; returns its name, or "" (unknown place, or already marked one this talk).
string Function Mark(string asPlace)
	If asPlace == "" || markedThisTalk
		Return ""
	EndIf
	string lower = Lower(asPlace)
	int id = JsonUtil.GetIntValue(MARKERS, lower, 0)
	string plugin = JsonUtil.GetStringValue(MARKERS, lower, "")
	If id == 0 || plugin == ""
		Return ""
	EndIf
	ObjectReference marker = Game.GetFormFromFile(id, plugin) as ObjectReference
	If !marker
		Return ""
	EndIf
	marker.AddToMap(false)
	markedThisTalk = true
	Return asPlace
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
