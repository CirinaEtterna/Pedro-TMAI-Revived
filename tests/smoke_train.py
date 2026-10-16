"""End-to-end smoke test of the Windows training pipeline against SimGame (no Trackmania needed).

    .venv\\Scripts\\python tests\\smoke_train.py [seconds] [extra train_windows.py args]

Runs the real train_windows.py setup (model, collector thread, replay buffer, learner, offline
checkpoints) for `seconds` and then sends a KeyboardInterrupt like Ctrl+C would.
"""
import _thread
import sys
import threading
from functools import cached_property
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "public-tmlearn")]

from sim_game import SimGame  # noqa: E402
from tmenv.tmenv import Tmenv  # noqa: E402
import train_windows  # noqa: E402

game = cached_property(lambda self: SimGame())
game.__set_name__(Tmenv, "game")
Tmenv.game = game

if __name__ == "__main__":
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 90
    threading.Timer(seconds, _thread.interrupt_main).start()
    train_windows.main(["--yes", "--map", "XJ_JEjWGoAexDWe8qfaOjEcq5l8", "--run-dir", str(ROOT / ".cache" / "smoke-runs"),
                        "--burnin", "256", "--buffer", "1024", "--episodes-per-map", "3", "--viewer-port", "2015"] + sys.argv[2:])
