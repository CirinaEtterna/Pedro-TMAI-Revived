[Setting name="Socket host" description="Socket host"]
string socket_host = '127.0.0.1';
[Setting name="Socket port" description="Socket port"]
int socket_port = 20131;

Net::Socket@ sock = null;
bool pause_telemetry = false;
bool telemetry_paused = false;

void Main() {
    ConnectSocket();
    startnew(ReceiveCommand);
    SendTelemetry();
    Reset();
}

bool TryConnect() {
    @sock = Net::Socket();
    if (!sock.Connect(socket_host, socket_port)) return false;
    // Connect is asynchronous: wait for the handshake, give up after 3 s (nothing listening yet) and retry
    uint64 start = Time::Now;
    while (!sock.IsReady()) {
        if (3000 < Time::Now - start) { sock.Close(); return false; }
        yield();
    }
    return true;
}

void ConnectSocket() {    while (!TryConnect()) sleep(1000);
    // (TryConnect waits for the socket to be ready)
    print("Connected to python script !");
    Telemetry::SendConfig(sock);
    print("Headers sent !");
}

void ReceiveCommand() {
    string received = '';
    while(sock !is null) {
        if (sock.Available() == 0) { yield(); continue; }
        received += sock.ReadRaw(512);
        while (received.Contains(';')) {
            auto split = received.Split(';', 2);
            received = received.SubStr(received.IndexOf(';') + 1);
            RunCommand(split[0]);
        }
    }
}

void RunCommand(string command) {
    auto split = command.Split('|');
    if (split[0] == 'LoadMap') {
        LoadMap(split[1]);
    }
    if (split[0] == 'LoadCampaignMap') {
        uint map_number = Text::ParseUInt(split[1]);
        auto map = GetCurrentOfficialCampaignMap(map_number-1);
        if (map is null) {
            warn('Campaign map #' + map_number + ' was not found.');
        } else {
            LoadMap(map.FileName);
        }
    }
    if (split[0] == 'SendGhost') {
        SendGhost(split[1], split[2]);
    }
    if (split[0] == 'SetResolution') {
        SetResolution(Text::ParseInt(split[1]), Text::ParseInt(split[2]));
    }
}

void LoadMap(string mapurl) {
    pause_telemetry = true;
    CTrackMania@ app = GetTmApp();
    while(!telemetry_paused) yield();
    app.BackToMainMenu();
    while(!app.ManiaTitleControlScriptAPI.IsReady) yield();
    app.ManiaTitleControlScriptAPI.PlayMap(
        mapurl,
        'TrackMania/TM_TimeAttack_Online.Script.txt',
        '<script_settings><setting name="S_TimeLimit" value="-1" type="integer"/><setting name="S_RespawnBehaviour" value="1" type="integer"/></script_settings>'
    );
    pause_telemetry = false;
}

void SendGhost(string ghost_url, string episode_id) {
    auto ghost = RetrieveGhost();
    if (ghost is null) return;
    GetDataFileMgr().Ghost_Upload(ghost_url, ghost, 'episode_id: ' + episode_id);
}

void SetResolution(int width, int height) {
    CGameManiaPlanetScriptAPI@ mp = GetManiaPlanet();
    mp.DisplaySettings_LoadCurrent();
    mp.DisplaySettings.DisplayMode = CGameDisplaySettingsWrapper::EDisplayMode::FullscreenExclusive;
    mp.DisplaySettings.FullscreenSize = int2(width, height);
    mp.DisplaySettings_Apply();
    mp.DisplaySettings_Unload();
}

void SendTelemetry() {
    bool connected = true;
    while (connected) {
        if (pause_telemetry) {
            telemetry_paused = true;
        } else {
            telemetry_paused = false;
            connected = Telemetry::Send(sock);
        }
        yield();
    }
}

void Reset() {
    print("Connection lost, resetting socket.");
    sock.Close();
    @sock = null;
    startnew(Main);
}