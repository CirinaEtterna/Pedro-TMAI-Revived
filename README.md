# Pedro-TMAI Revived: PedroAI

> **In honor of Pedro.** Pedro started PedroAI in April 2020, streamed its training on Twitch from
> April 2021 to September 2023, and then open-sourced it. On **October 15, 2026**, one month before his
> birthday (November 15), we picked his work up again. The AI and this project carry his name.

Windows port of the open-sourced [PedroAI](https://github.com/trackmania-ai) Trackmania AI. It's a
DQN agent that drives Trackmania 2020 from the game image plus Openplanet telemetry. The original
targets Linux (wine, firejail, X11, evdev), and this setup runs it on a native Windows Trackmania.
Double-click `PedroAI.bat` to run it.

## Layout

| Path | What |
|---|---|
| `PedroAI.bat` | double-click: run the AI + viewer (same commands as `tmai.bat`) |
| `tmai.bat` | entry point: no argument = run the AI + viewer; `new`, `check`, `install-plugin`, `train`, `smoke-test` |
| `public-tmenv/` | game environment, Windows backend in `tmenv/win32.py` (upstream history included) |
| `public-tmlearn/` | DQN training, `train_windows.py`, viewer, live parameters (upstream history included) |
| `public-op-aitool/` | AITool Openplanet plugin (telemetry + map loading over a socket) |
| `runs/<run name>/` | created by training (not in git): `agent-latest.pth`, snapshots, `demos.pt`, `run_config.json`, `params.json`, logs |
| `tests/` | simulator, smoke tests, benchmarks, live diagnostics |
| `.venv`, `.cache`, `tools` | created by the setup below (not in git): Python 3.12 env, caches, .NET runtime, uv |

On the original machine `.venv`, `.cache` and `tools` are junctions to another drive: D: is formatted
with 2 MB clusters, so the ~40,000 small files of the Python environment would take ~80 GB there. If
your drive uses large clusters too, create them on another drive and link them in with `mklink /J`.

## Setup on a new machine

Needs Windows 10/11, an NVIDIA GPU with a recent driver (CUDA 13), and Trackmania 2020 with Club access
(see the game setup below). From a terminal:

```
git clone https://github.com/CirinaEtterna/Pedro-TMAI-Revived
cd Pedro-TMAI-Revived
powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
uv venv .venv --python 3.12
uv pip install --python .venv\Scripts\python.exe torch==2.14.1 torchvision --index-url https://download.pytorch.org/whl/cu130
uv pip install --python .venv\Scripts\python.exe -e public-tmenv -e public-tmlearn --index-url https://pypi.org/simple --extra-index-url https://download.pytorch.org/whl/cu130 --index-strategy unsafe-best-match
powershell -ExecutionPolicy Bypass -c "& ([scriptblock]::Create((irm https://dot.net/v1/dotnet-install.ps1))) -Runtime dotnet -Channel 10.0 -InstallDir tools\dotnet"
tmai install-plugin
tmai check
```

The .NET runtime is used by GbxToJson to read maps and ghosts. Its assemblies are extracted from the
bundled upstream binary the first time a map is loaded.

## One-time game setup

1. **Openplanet** must be installed in the Trackmania folder you play with
   (`D:\SteamLibrary\steamapps\common\Trackmania`).
2. **Developer signature mode.** AITool is unsigned, so it only loads in Developer mode, which
   **requires Club access** and puts the game in **School mode** (no online play or records). Select it
   in game: **F3 > Openplanet > Signature Mode > Developer**. `DeveloperMode=true` is also set in
   `%USERPROFILE%\OpenplanetNext\Settings.ini` (original backed up as `Settings.ini.before-tmai.bak`),
   but on Openplanet 1.29 that alone did not switch the mode; `tmai check` tells you whether Openplanet
   actually loaded AITool. To play normally, switch back to Regular in the same menu.
3. **AITool plugin**: `tmai install-plugin` (already done; rerun after changing `public-op-aitool`).
4. **Trackmania settings** (from the original author's setup):
   - Video: DISPLAY MODE **WINDOWED**, DYNAMIC RESOLUTION disabled, FRAME RATE LIMIT 150,
     V-SYNC none, GPU & CPU SYNCHRONIZATION none, advanced video preset VERY FAST, MOTION BLUR disabled.
     The AI resizes the window so the game area is 960x540.
   - Sound: ENABLE AUDIO disabled (optional).
   - HUD: VISIBILITY OF THE CAR IN COCKPIT VIEW transparent, DEFAULT OPPONENT VISIBILITY hidden.
   - System: SKIP THE START-UP SCREENS enabled.
   - Controls, keyboard defaults: Accelerate `Up`, Brake `Down`, Steer `Left`/`Right`,
     Give up `Delete`, Respawn `Backspace`, Show/hide interface `Numpad *`.
5. In any race, switch to the **cockpit camera (3)** and hide your ghost (**G**). The game remembers both.

Then start Trackmania, open any map and run:

```
tmai check --inputs
```

Every line should be `[ OK ]`. The input test sends arrow keys and Delete to the game window and
prints the input latency (about 40-60 ms from key press to telemetry). `check_capture.png` shows what
the AI sees. `python tmai.py ...` works too: it re-runs itself inside `.venv`.

After editing the plugin (`public-op-aitool`), run `tmai install-plugin`, then in game
F3 > Developer > Reload plugin. Two diagnostics live in `tests\`: `dump_telemetry.py` captures raw plugin
bytes and detects the frame size/byte order, `trace_inputs.py` sends the key sequence while logging the
telemetry at 20 Hz.

## Training

Double-click `PedroAI.bat` or `tmai.bat` (or run `tmai` from `D:\TMAI`). It resumes your latest run, or starts one
when there is none, and opens the viewer in your browser as soon as it is up. The window stays open
at the end so you can read the last messages. Options can be added: `tmai --master-learn`,
`tmai --no-open-viewer`, and any `tmai train` option.

```
tmai new
```

- Starts a new run in `runs\<three-word-name>` (with the viewer). The default schedule is the white,
  green and blue maps of the 13 first official campaigns (195 maps), 10 episodes per map, like the
  original. `tmai new --map <uid>` trains on one map.
- Each run saves its settings (map, schedule, buffer, burn-in, reward, ...) in `run_config.json`;
  resuming reuses them unless you pass a different value.
- `tmai train [options]` is the same without the browser and without picking the run for you
  (`--resume <run name>` to continue one).
- The AI downloads each map and its world-record ghost from trackmania.io. The ghost line is the
  reference trajectory for the reward. The plugin loads the map in game.
- **Keep the Trackmania window visible and in the foreground.** Keys are only sent while Trackmania
  is focused. If you click elsewhere, inputs pause, those steps are not learned from, and the AI takes
  focus back within ~2 s (`--no-focus-steal` to disable that and wait for you instead).
- **Ctrl+C** stops training and saves the agent and training state. Checkpoints are also saved every
  10 minutes, with a dated snapshot every 6 hours.
- Resume: `tmai train --resume <run name>`.
- Train on a single map: `tmai train --map <map uid>`, for example `XJ_JEjWGoAexDWe8qfaOjEcq5l8`
  (Summer 2020 - 01).
- Timing: actions are kept 100 ms apart (`fixed_period`): the sleep after each action is shortened by
  the time the previous step's processing took, so the observation comes ~60 ms after the action
  instead of 100 ms, and the agent acts at 10 Hz. `--no-fixed-period` restores the upstream timing
  (100 ms sleep plus ~40 ms processing, about 7 Hz). Each episode logs its actual `step_period`.
- Game performance: the learner shares the GPU with the game. Cap the game at 60 FPS (in-game limit
  or RivaTuner): the AI samples at 10 Hz and the plugin still sends telemetry every frame. Graphics
  settings change what the AI sees, so pick them once (the author's: VERY FAST preset, no
  antialiasing, no motion blur, transparent car in cockpit view) and don't change them during a
  training run.
- All options: `tmai train --help` (`--launch steam`, `--buffer`, `--burnin`, `--lr`, `--wandb`, ...).

Progress is printed per episode (progress along the map, finish time, medal) and logged in
`runs\<name>\episodes.jsonl`. Learner metrics go to `metrics.jsonl`. Expect it to be slow: the
original AI trained for months on three game instances, and the first finishes on easy maps take hours.

`tmai smoke-test 120` runs the whole pipeline against a simulated game (no Trackmania needed). It's
handy after changing code.

## Reward, viewer and master-learn

- **Reward** (`--reward distance`, the default): the dominant signal is the distance covered along the
  track, `travel_weight` per 10 m of new progress (less when far from the reference line). A mistake
  (off the line or not progressing) costs `mistake_penalty` per step, a forced respawn or give-up
  `respawn_penalty`, finishing earns `finish_bonus`. With this reward the forced respawn / give-up
  transitions are learned from (upstream dropped them). `--reward upstream` restores the original
  speed-along-the-line reward; its weights are fixed, so the viewer's Reward panel has no effect then.
- **Viewer**: every run serves `http://127.0.0.1:2014` (`--viewer-port`, `--no-viewer`), open it in
  your own browser, ideally on another monitor (anything that takes the foreground pauses the AI's
  inputs until it takes focus back): what the AI
  sees, speed / progress / reward, the Q-value of each action (the chosen one highlighted, yours in
  master-learn), episode and loss charts, and the **parameters** panel. Applying it writes
  `runs\<run>\params.json`, which the learner and the collector pick up within a step: reward weights,
  seconds of mistake before a respawn, exploration (upstream cycle / fixed epsilon / greedy), learning
  rate multiplier, batch size, demonstration priority bonus. You can also edit the file by hand.
- **Master-learn** (`--master-learn`, or the checkbox in the viewer; `--no-master-learn` forces it
  off): you drive, the AI watches. It stops sending keys, waits for you to (re)start the race (Delete),
  reads your inputs from the telemetry as actions and stores each step as a protected demonstration
  (never overwritten in the replay buffer, DQfD-style priority bonus). Restarting the race ends the
  demonstration episode. Demonstrations are saved to `runs\<run>\demos.pt` on checkpoints and
  reloaded with `--resume` (or imported into another run with `--demos <run>`), so the AI keeps
  learning from your runs after you hand control back, by unticking the box or `--no-master-learn`.
  Steps before your car first moves are not recorded. Demonstrations may use up to 80% of the replay
  buffer (`--buffer`, default 8192: about 11 minutes of driving); past that they are stored as
  ordinary experiences and a warning is logged once. About 10 Hz x 400 KB per step: a 5-minute session
  is roughly 1.2 GB on disk and in VRAM. Telemetry pauses while your car respawns, so the telemetry
  timeouts are 10x longer in master-learn.

## What changed from upstream

- **tmenv**
  - New Windows backend (`tmenv/win32.py`). It attaches to or launches the real game, injects keys
    with `SendInput` scan codes (focus-guarded, released on exit) and captures the window with `mss`.
    Analog steering through a virtual pad is optional (`--analog-steer`, needs vgamepad + ViGEmBus).
  - Robust socket framing. The 2,036-byte header was read with a 2,048-byte `recv`, and partial
    reads broke frames.
  - Fixed AITool port 20131.
  - GbxToJson runs on Windows: the managed GBX.NET dlls were extracted from the Linux bundle and run
    on .NET 10.
  - New trackmania.io campaign endpoints.
  - Migrated from `gym` to `gymnasium`.
  - Optional uint8 frames: the replay buffer uses ~3 GB of VRAM instead of ~13 GB.
  - `RotationEnvWrapper` crashed (`int has no attribute item`) when two telemetry frames arrived
    within 0.1 ms of each other, which happens on Windows because the plugin's TCP writes batch up.
- **tmlearn**
  - The collector runs in its own process, as upstream, but Windows has no CUDA IPC: experiences cross
    the process boundary as CPU tensors (the learner moves them back to the GPU), the collector holds
    its own copy of the network and the learner publishes a CPU weight snapshot every 10 s. On Ctrl+C
    the learner signals the collector, which releases the game keys and exits cleanly.
    `TMLEARN_WORKERS=threads` runs the collector as a thread instead (slower: GIL contention).
  - Offline mode with local checkpoints and resume, so a wandb account is optional.
  - `torch.amp` instead of the deprecated `torch.cuda.amp`.
  - TD targets computed in float32. The eval-mode target net overflowed float16, which caused
    nan priorities.
  - Clean Ctrl+C.
- **AITool** (ported to Openplanet 1.29):
  - `string::Join` moved to `Text::Join` (the plugin did not compile).
  - `Net::Socket::Connect` is asynchronous now: the old loop hung forever on a failed first attempt.
    `TryConnect()` waits for `IsReady()` with a 3 s timeout and retries.
  - Enum fields are written as explicit 4-byte uints: Openplanet now writes `EPlugSurfaceMaterialId`
    (wheel contact material) as 1 byte, which shifted every frame by 12 bytes.
  - The `speed` telemetry field is a float (it was declared uint).
- **Packaging**: `setup.py` no longer needs `pkg_resources`, and the Linux-only dependencies are
  marked Linux-only.
