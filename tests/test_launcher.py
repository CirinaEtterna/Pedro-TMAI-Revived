"""Launcher test: tmai.run() (the default `tmai` command) against the simulated game."""
import _thread
import sys
import threading
from functools import cached_property
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "public-tmlearn"), str(ROOT)]

from sim_game import SimGame  # noqa: E402
from tmenv.tmenv import Tmenv  # noqa: E402

game = cached_property(lambda self: SimGame())
game.__set_name__(Tmenv, "game")
Tmenv.game = game

import tmai  # noqa: E402

if __name__ == "__main__":
    import torch.multiprocessing as mp

    mp.set_start_method("spawn", force=True)
    threading.Timer(float(sys.argv[1]), _thread.interrupt_main).start()
    tmai.run(sys.argv[2:])
