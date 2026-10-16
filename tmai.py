"""PedroAI (trackmania-ai) on Windows: setup checks, plugin install, training.

    tmai [options]            run the AI: resume the latest run (or start one) and open the viewer
    tmai new [options]        start a new run and open the viewer
    tmai check [--inputs]     verify every piece of the setup, step by step
    tmai install-plugin       copy the AITool Openplanet plugin into OpenplanetNext\\Plugins
    tmai train [options]      train the AI (tmai train --help for options)
    tmai smoke-test [seconds] run the training pipeline against a simulated game
"""
import argparse
import configparser
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

if VENV_PYTHON.exists() and Path(sys.executable).resolve() != VENV_PYTHON.resolve():
    # Started with another Python (e.g. `python tmai.py`): re-run inside the project environment,
    # with the same environment variables tmai.bat sets.
    import subprocess

    os.environ.setdefault("HF_HOME", str(ROOT / ".cache" / "huggingface"))
    os.environ.setdefault("TMENV_DOTNET", str(ROOT / "tools" / "dotnet" / "dotnet.exe"))
    os.environ.setdefault("PYTHONWARNINGS", "ignore::FutureWarning,ignore::UserWarning")
    sys.exit(subprocess.call([str(VENV_PYTHON), __file__] + sys.argv[1:]))

PLUGIN_SRC = ROOT / "public-op-aitool"
PLUGIN_FILES = ["info.toml", "AITool.as", "Nod.as", "Telemetry.as"]
OPENPLANET_DIR = Path(os.environ.get("USERPROFILE", "~")).expanduser() / "OpenplanetNext"
PLUGIN_DST = OPENPLANET_DIR / "Plugins" / "AITool"
TEST_MAP_UID = "XJ_JEjWGoAexDWe8qfaOjEcq5l8"  # Summer 2020 - 01

OK, WARN, FAIL = "  [ OK ]", "  [WARN]", "  [FAIL]"


def step(title):
    print(f"\n== {title}")


def game_dirs():
    "Trackmania install folders: running process first, then Steam libraries and Ubisoft Connect."
    import psutil

    dirs = []
    for p in psutil.process_iter(["name", "exe"]):
        if (p.info["name"] or "").lower() == "trackmania.exe" and p.info["exe"]:
            dirs.append(Path(p.info["exe"]).parent)
    steam_vdf = Path(r"C:\Program Files (x86)\Steam\steamapps\libraryfolders.vdf")
    if steam_vdf.exists():
        import re

        for lib in re.findall(r'"path"\s+"([^"]+)"', steam_vdf.read_text(errors="ignore")):
            dirs.append(Path(lib.replace("\\\\", "\\")) / "steamapps" / "common" / "Trackmania")
    dirs += [Path(r"C:\Program Files (x86)\Ubisoft\Ubisoft Game Launcher\games\Trackmania"),
             Path(r"C:\Program Files\Ubisoft\Ubisoft Game Launcher\games\Trackmania")]
    seen, result = set(), []
    for d in dirs:
        if (d / "Trackmania.exe").exists() and str(d).lower() not in seen:
            seen.add(str(d).lower())
            result.append(d)
    return result


# %% install-plugin
def install_plugin(_args=None):
    if not OPENPLANET_DIR.exists():
        print(f"{FAIL} {OPENPLANET_DIR} not found: install Openplanet and start Trackmania once first.")
        return False
    PLUGIN_DST.mkdir(parents=True, exist_ok=True)
    for f in PLUGIN_FILES:
        shutil.copy2(PLUGIN_SRC / f, PLUGIN_DST / f)
    print(f"{OK} AITool plugin copied to {PLUGIN_DST}")
    print("       In game: F3 > Developer > Reload plugin > AITool (or restart Trackmania).")
    return True


# %% check
def check(args):
    results = []

    step("1. Python, PyTorch and GPU")
    import torch

    print(f"{OK} Python {sys.version.split()[0]}, PyTorch {torch.__version__}")
    if torch.cuda.is_available():
        print(f"{OK} CUDA device: {torch.cuda.get_device_name(0)}")
    else:
        print(f"{FAIL} CUDA is not available: training would run on CPU")
        results.append(False)

    step("2. Map download and GBX parsing (trackmania.io + GbxToJson on .NET)")
    try:
        from tmenv.gbx import map_from_uid

        m = map_from_uid(TEST_MAP_UID)
        print(f"{OK} {m['name']}: {m['nb_checkpoints']} checkpoints, reference ghosts: {list(m['ghosts'])}")
    except Exception as e:
        print(f"{FAIL} {type(e).__name__}: {e}")
        results.append(False)

    step("3. Trackmania and Openplanet installs")
    dirs = game_dirs()
    if not dirs:
        print(f"{FAIL} Trackmania.exe not found (start the game and rerun the check)")
        results.append(False)
    for d in dirs:
        op_files = [p.name for p in d.iterdir() if p.name.lower().startswith("openplanet")]
        print(f"{OK if op_files else FAIL} {d}: {'Openplanet files ' + str(op_files) if op_files else 'Openplanet is NOT installed here'}")
        if not op_files:
            results.append(False)

    step("4. AITool plugin and Openplanet developer mode")
    if not OPENPLANET_DIR.exists():
        print(f"{FAIL} {OPENPLANET_DIR} does not exist")
        results.append(False)
    else:
        installed = all((PLUGIN_DST / f).exists() for f in PLUGIN_FILES)
        same = installed and all((PLUGIN_DST / f).read_bytes() == (PLUGIN_SRC / f).read_bytes() for f in PLUGIN_FILES)
        if same:
            print(f"{OK} AITool installed in {PLUGIN_DST}")
        else:
            print(f"{FAIL if not installed else WARN} AITool {'is not installed' if not installed else 'differs from the repo'}: run `tmai install-plugin`")
            results.append(installed)
        settings = OPENPLANET_DIR / "Settings.ini"
        dev = None
        if settings.exists():
            for line in settings.read_text(errors="ignore").splitlines():
                if line.strip().lower().startswith("developermode="):
                    dev = line.split("=", 1)[1].strip().lower() == "true"
        print(f"{OK if dev else WARN} Developer mode at startup: {dev}. Unsigned plugins like AITool only load in "
              "Developer signature mode (F3 > Openplanet > Signature Mode > Developer, needs Club access).")
        log = OPENPLANET_DIR / "Openplanet.log"
        if log.exists():
            text = log.read_text(errors="ignore")
            if "Loaded plugin 'AITool'" in text or "Loaded plugin 'AI Tool'" in text:
                print(f"{OK} Openplanet loaded AITool in its last session (Openplanet.log)")
            else:
                print(f"{WARN} Openplanet did NOT load AITool in its last session: it was not in Developer signature "
                      "mode. In game: F3 > Openplanet > Signature Mode > Developer, then restart Trackmania "
                      "(or F3 > Developer > Load plugin > AITool).")
            club = [l for l in text.splitlines() if "Club access" in l or "Club / Standard" in l]
            if club:
                print(f"{WARN} Some plugins reported missing Club access (Developer mode needs Club): {club[-1].strip()[:110]}")
            for l in [l for l in text.splitlines() if "AITool" in l or "AI Tool" in l][-6:]:
                print(f"       log: {l.strip()}")

    step("5. Trackmania window")
    from tmenv.win32 import TmWindow, find_game_windows

    windows = find_game_windows()
    window = TmWindow(windows[0]) if windows else None
    if window is None:
        print(f"{FAIL} No Trackmania window: start the game, then rerun the check")
        results.append(False)
    else:
        from tmenv.win32 import user32

        windowed = bool(user32.GetWindowLongW(window.hwnd, -16) & 0x00C00000)
        print(f"{OK} Window found, client area {window.client_rect()} ({'windowed' if windowed else 'fullscreen/borderless'})")
        if not windowed:
            print(f"{WARN} Use DISPLAY MODE: WINDOWED so the AI can size the game to 960x540.")

    step("6. AITool telemetry connection")
    socket = None
    if window is not None:
        from tmenv.socket import Socket

        try:
            socket = Socket(port=args.port)
        except OSError:
            print(f"{FAIL} Port {args.port} is busy (is a training already running?)")
        if socket is not None:
            print(f"       Waiting up to {args.timeout}s for AITool to connect on 127.0.0.1:{args.port} ...")
            start = time.time()
            while not socket.connected and time.time() - start < args.timeout:
                time.sleep(0.2)
            if not socket.connected:
                print(f"{FAIL} AITool did not connect. Check Developer mode, that AITool is loaded (F3 > Developer > "
                      "Plugins), and the Openplanet log (F3 > Openplanet > Log).")
                results.append(False)
            else:
                print(f"{OK} AITool connected")
                start = time.time()
                while not socket.telemetry and time.time() - start < 10:
                    time.sleep(0.1)
                if not socket.telemetry:
                    print(f"{WARN} Connected but no telemetry yet: telemetry only flows while driving (start any map).")
                else:
                    n, t0, last = 0, time.time(), None
                    while time.time() - t0 < 2:
                        t = socket.telemetry
                        if t is not last:
                            n, last = n + 1, t
                        time.sleep(0.0005)
                    t = socket.telemetry
                    print(f"{OK} Telemetry at ~{n / 2:.0f} Hz: racetime {t['racetime']} ms, speed {t['speed']:.0f}, "
                          f"position {[round(v, 1) for v in t['position']]}, ui_sequence {t['ui_sequence']}")

    step("7. Screen capture")
    if window is not None:
        try:
            t = time.time()
            for _ in range(10):
                frame = window.capture_tensor()
            dt = (time.time() - t) / 10 * 1000
            out = ROOT / "check_capture.png"
            window.capture_image().save(out)
            print(f"{OK} Captured {tuple(frame.shape)} in {dt:.1f} ms per frame, saved {out} (it must show the game, not another window)")
        except Exception as e:
            print(f"{FAIL} {e}")
            results.append(False)

    if args.inputs:
        step("8. Keyboard inputs (Trackmania must be in a race)")
        results.append(check_inputs(window, socket))

    print()
    if all(r is not False for r in results):
        print("All checks passed." if not results or all(results) else "Checks finished with warnings.")
    else:
        print("Some checks failed, see [FAIL] above.")
    if socket is not None:
        socket.close()


def check_inputs(window, socket):
    if window is None or socket is None or not socket.telemetry:
        print(f"{FAIL} Needs the game window and live telemetry (be in a race on any map).")
        return False
    from tmenv.win32 import send_keys

    if not window.focus():
        print(f"{FAIL} Could not bring Trackmania to the foreground: click on the game and rerun.")
        return False

    def wait_until(cond, timeout):
        start = time.time()
        while time.time() - start < timeout:
            if cond(socket.telemetry):
                return True
            time.sleep(0.01)
        return False

    def hold(keys, seconds, probe):
        "Hold `keys` for `seconds`; return the delay until `probe` holds on the telemetry (None if never)."
        send_keys(keys)
        start, delay = time.time(), None
        while time.time() - start < seconds:
            if delay is None and probe(socket.telemetry):
                delay = time.time() - start
            time.sleep(0.005)
        send_keys(keys, up=True)
        time.sleep(0.3)
        return delay

    def restart():
        "Give up and wait for the race to restart (racetime goes negative during the countdown, then positive at GO)."
        wait_until(lambda t: 0 < t["racetime"], 5)
        before = socket.telemetry["racetime"]
        window.give_up()
        restarted = wait_until(lambda t: t["racetime"] < before - 500, 3)
        go = restarted and wait_until(lambda t: 0 < t["racetime"], 5)
        return restarted, go

    ok = True
    restarted, go = restart()
    if not go:
        print(f"{FAIL} Delete (give up / restart): the race did not restart. Are you in a race with the game focused?")
        return False
    tests = [
        ("Up (accelerate)", ["Up"], 1.0, lambda t: t["accelerate"] > 0.5),
        ("Down (brake)", ["Down"], 0.5, lambda t: bool(t["brake"])),
        ("Left (steer)", ["Left"], 0.5, lambda t: t["steer"] < -0.5),
        ("Right (steer)", ["Right"], 0.5, lambda t: t["steer"] > 0.5),
    ]
    for name, keys, seconds, probe in tests:
        delay = hold(keys, seconds, probe)
        ok &= delay is not None
        print(f"{OK} {name}: registered after {delay * 1000:.0f} ms" if delay is not None else f"{FAIL} {name}")
    restarted, go = restart()
    ok &= restarted
    print(f"{OK if restarted else FAIL} Delete (give up / restart)")
    if not ok:
        print("       Check Settings > Controls > Keyboard: Accelerate=Up, Brake=Down, Steer=Left/Right, "
              "Give up=Delete, Respawn=Backspace, Show/hide interface=Numpad *.")
    return ok


# %% run / new / train / smoke-test
def latest_run(run_dir=ROOT / "runs"):
    "Name of the run whose agent was saved last, None when there is none."
    runs = [p for p in Path(run_dir).glob("*") if (p / "agent-latest.pth").exists()] if Path(run_dir).exists() else []
    return max(runs, key=lambda p: (p / "agent-latest.pth").stat().st_mtime).name if runs else None


def option(argv, name, default=None):
    "Value of `--name value` in argv."
    return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else default


def open_viewer_when_ready(port, timeout=600):
    "Open the viewer in the default browser as soon as the training serves it."
    import socket
    import threading
    import webbrowser

    def wait():
        start = time.time()
        while time.time() - start < timeout:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    webbrowser.open(f"http://127.0.0.1:{port}")
                    return
            except OSError:
                time.sleep(1)

    threading.Thread(target=wait, daemon=True, name="open-viewer").start()


def run(argv, new=False):
    "Resume the latest run (or start a new one) with the viewer opened in the browser."
    argv = list(argv)
    open_viewer = "--no-open-viewer" not in argv and "--no-viewer" not in argv
    argv = [a for a in argv if a != "--no-open-viewer"]
    if "--resume" in argv:
        resume = option(argv, "--resume")
    else:
        resume = None if new else latest_run(ROOT / option(argv, "--run-dir", "runs"))
        argv = (["--resume", resume] if resume else ["--yes"]) + argv
    config_path = ROOT / option(argv, "--run-dir", "runs") / (resume or "") / "run_config.json"
    config = {}
    if resume and config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        except ValueError as e:
            print(f"  (ignoring unreadable {config_path}: {e})")
    track = option(argv, "--map") or config.get("map")
    port = int(option(argv, "--viewer-port", config.get("viewer_port", 2014)))
    print("=" * 78)
    print("  PedroAI, continuing Pedro's work since October 15, 2026")
    print(f"  {'Resuming run ' + repr(resume) if resume else 'Starting a new run'}"
          f" ({'map ' + track if track else 'official campaign schedule'})")
    if resume:
        print("  (new run: tmai new, other options: tmai train --help)")
    if open_viewer:
        print(f"  Viewer: http://127.0.0.1:{port} (opens in your browser when ready)")
    print("  Start Trackmania (Openplanet in Developer mode) if it isn't running.")
    print("  Ctrl+C here stops the AI and saves the run.")
    print("=" * 78)
    if open_viewer:
        open_viewer_when_ready(port)
    train(argv)


def train(argv):
    sys.path.insert(0, str(ROOT / "public-tmlearn"))
    import train_windows

    os.chdir(ROOT)
    train_windows.main(argv)


def smoke_test(argv):
    # Own interpreter so that spawned collector processes re-import smoke_train.py (and its simulated game)
    import subprocess

    sys.exit(subprocess.call([sys.executable, str(ROOT / "tests" / "smoke_train.py")] + argv, cwd=str(ROOT)))


def main():
    first = sys.argv[1] if len(sys.argv) > 1 else None
    if first is None or first in ("run", "new", "train", "smoke-test") or (first.startswith("-") and first not in ("-h", "--help")):
        import torch.multiprocessing as mp

        mp.set_start_method("spawn", force=True)
        if first is None or first.startswith("-"):
            return run(sys.argv[1:])
        commands = dict(run=run, new=lambda argv: run(argv, new=True), train=train, smoke_test=smoke_test)
        return commands[first.replace("-", "_")](sys.argv[2:])
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="run the AI: resume the latest run (or start one) and open the viewer (default)")
    sub.add_parser("new", help="start a new run and open the viewer")
    c = sub.add_parser("check", help="verify the setup")
    c.add_argument("--inputs", action="store_true", help="also test keyboard control (be in a race)")
    c.add_argument("--port", type=int, default=20131)
    c.add_argument("--timeout", type=int, default=30, help="seconds to wait for the plugin connection")
    sub.add_parser("install-plugin", help="install the AITool Openplanet plugin")
    sub.add_parser("train", help="train the AI (tmai train --help)")
    sub.add_parser("smoke-test", help="run the pipeline on a simulated game")
    args = p.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    {"check": check, "install-plugin": install_plugin}[args.command](args)


if __name__ == "__main__":
    main()
