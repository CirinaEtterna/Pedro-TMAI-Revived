CTrackMania@ GetTmApp() {
    return cast<CTrackMania>(GetApp());
}

CGameManiaTitleControlScriptAPI@ GetTitleControl() {
    return GetTmApp().ManiaTitleControlScriptAPI;
}

CGameManiaPlanetScriptAPI@ GetManiaPlanet() {
    return GetTmApp().ManiaPlanetScriptAPI;
}

CTrackManiaMenus@ GetMenuManager() {
    if (GetTmApp().MenuManager is null) return null;
    return cast<CTrackManiaMenus>(GetTmApp().MenuManager);
}

CGameManiaAppTitle@ GetManiaAppTitle()
{
    auto mm = GetMenuManager();
    if (mm is null) return null;
    return mm.MenuCustom_CurrentManiaApp;
}

CGameUILayer@ GetUILayer(string attach_id) {
    auto mania_app = GetManiaAppTitle();
    if (mania_app is null) return null;
    for (uint i = 0; i < mania_app.UILayers.Length; ++i) {
        if (mania_app.UILayers[i].AttachId == attach_id) return mania_app.UILayers[i];
    }
    return null;
}

CGameUILayer@ RunManialink(string attach_id, string manialink) {
    CGameManiaAppTitle@ mania_app = GetManiaAppTitle();
    if (mania_app is null) return null;
    CGameUILayer@ layer = GetUILayer(attach_id);
    if (layer !is null) mania_app.UILayerDestroy(layer);
    @layer = mania_app.UILayerCreate();
    layer.ManialinkPage = manialink;
    layer.AttachId = attach_id;
    layer.IsVisible = false;
    return layer;
}

CSmArenaRulesMode@ GetPlaygroundScript() {
    if (GetTmApp().PlaygroundScript is null) return null;
    return cast<CSmArenaRulesMode>(GetTmApp().PlaygroundScript);
}

CSmScriptPlayer@ GetScriptPlayer() {
    auto cp = GetCurrentPlayground();
    if (cp is null || cp.GameTerminals.Length == 0) {
        return null;
    }
    auto terminal = cp.GameTerminals[0];
    if (terminal.ControlledPlayer is null) {
        return null;
    }
    auto sm_player = cast<CSmPlayer>(terminal.ControlledPlayer);
    return cast<CSmScriptPlayer>(sm_player.ScriptAPI);
}

CGameGhostScript@ RetrieveGhost() {
    CSmArenaRulesMode@ ps = GetPlaygroundScript();
    if (ps is null) return null;
    CSmScriptPlayer@ sp = GetScriptPlayer();
    if (sp is null) return null;
    return ps.Ghost_RetrieveFromPlayer(sp);
}

CSmArenaClient@ GetCurrentPlayground() {
    if (GetTmApp().CurrentPlayground is null) return null;
    return cast<CSmArenaClient>(GetTmApp().CurrentPlayground);
}

CSmArenaInterfaceUI@ GetInterface() {
    auto cp = GetCurrentPlayground();
    if (cp is null || cp.Interface is null) return null;
    return cast<CSmArenaInterfaceUI>(cp.Interface);
}

CControlFrame@ GetInterfaceRoot() {
    auto i = GetInterface();
    if (i is null || i.InterfaceRoot is null) return null;
    return cast<CControlFrame>(i.InterfaceRoot);
}

CGameMatchSettingsManagerScript@ GetMatchSettingsManagerScript() {
    return GetTmApp().MatchSettingsManagerScript;
}

CGameMatchSettingsScript@ GetMatchSetting(string name) {
    auto msm = GetMatchSettingsManagerScript();
    if (msm is null) return null;
    for (uint i = 0; i < msm.MatchSettings.Length; i++) {
        if (msm.MatchSettings[i].Name == name) return msm.MatchSettings[i];
    }
    return null;
}

CGameScriptMapLandmark@ GetLandmark(uint lm_id = 0) {
    auto playground = GetPlaygroundScript();
    if (playground is null) return null;
    auto lms = playground.MapLandmarks;
    if (lm_id < 0 || (lms.Length - 1) < lm_id) return null;
    return lms[lm_id];
}

CGameScriptMapLandmark@ GetSpawnLandmark() {
    auto ps = GetPlaygroundScript();
    if (ps is null) return null;
    return ps.MapLandmarks_PlayerSpawn[0];
}

int GetSpawnLandmarkId() {
    auto spawn = GetSpawnLandmark();
    if (spawn is null) return -1;
    auto ps = GetPlaygroundScript();
    if (ps is null) return -1;
    auto lms = ps.MapLandmarks;
    for (uint i = 0; i < lms.Length; i++) {
        if (spawn is lms[i]) return i;
    }
    return -1;
}

int GetRaceTime(CSmScriptPlayer& sapi)
{
    // not playing
	if (sapi is null) return 0;
    auto ps = GetPlaygroundScript();
    // online ? online now : solo now
    auto now = ps is null ? GetApp().Network.PlaygroundClientScriptAPI.GameTime : ps.Now;
    return now - sapi.StartTime;
}

string Vec3ToJson(vec3&in vec) {
    return "[" + vec.x + "," + vec.y + "," + vec.z + "]";
}

uint GetNbPlayers() {
    auto cp = GetCurrentPlayground();
    if (cp is null) return 0;
    return cp.GameTerminals.Length;
}

string GetMapName() {
    auto cp = GetCurrentPlayground();
    if (cp is null) return "";
    return cp.Map.MapInfo.Name;
}

bool Finished() {
    auto cp = GetCurrentPlayground();
    if (cp is null || cp.GameTerminals.Length == 0) {
        return false;
    }
    auto terminal = cp.GameTerminals[0];
    return (
        terminal.UISequence_Current == SGamePlaygroundUIConfig::EUISequence::EndRound
        || terminal.UISequence_Current == SGamePlaygroundUIConfig::EUISequence::Finish
    );
}

CGameDataFileManagerScript@ GetDataFileMgr()
{
    auto ps = GetPlaygroundScript();
    if (ps is null) return null;
    return cast<CGameDataFileManagerScript>(ps.DataFileMgr);
}

CInputScriptPad@ GetScriptPad(string pad_name) {
    auto ip = GetTmApp().InputPort;
    if (ip is null) return null;
    auto sps = ip.Script_Pads;
    for (uint i = 0; i < sps.Length; i++) {
        if (pad_name == sps[i].ModelName) return sps[i];
    }
    return null;
}

CGameCtnChallengeInfo@ GetCurrentOfficialCampaignMap(uint index) {
    auto ocs = GetTmApp().OfficialCampaigns;
    if (ocs.Length < 1) return null;
    auto mgs = ocs[0].MapGroups;
    if (mgs.Length < 1) return null;
    auto mis = mgs[0].MapInfos;
    if (mis.Length <= index) return null;
    return mis[index];
}