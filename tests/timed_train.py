"""Timed live training run on the real game: stops with a KeyboardInterrupt (like Ctrl+C) after N seconds.

    .venv\Scripts\python tests\timed_train.py <seconds> [train_windows.py args]
"""
import _thread
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "public-tmlearn"))
import train_windows  # noqa: E402

if __name__ == "__main__":
    threading.Timer(float(sys.argv[1]), _thread.interrupt_main).start()
    train_windows.main(["--yes"] + sys.argv[2:])
