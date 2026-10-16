"""Tunable training parameters shared live between the learner, the collector processes and the viewer.

They live in `<run dir>/params.json`: the viewer (or a text editor) writes it, every process polls the
file's modification time and applies changes within a step.
"""

__all__ = ['SCHEMA', 'DEFAULTS', 'TunableParams']

import json
import os
from pathlib import Path

SCHEMA = [
    dict(name="master_learn", type="bool", default=False, group="Master-learn",
         label="I drive, the AI watches and records my runs as demonstrations (applies at the next episode)"),
    dict(name="demo_priority_bonus", type="float", default=1.0, min=0.0, max=10.0, step=0.1, group="Master-learn",
         label="Replay priority bonus of my demonstrations"),
    dict(name="travel_weight", type="float", default=1.0, min=0.0, max=10.0, step=0.1, group="Reward",
         label="Reward per 10 m of new progress along the track"),
    dict(name="mistake_penalty", type="float", default=0.5, min=0.0, max=20.0, step=0.1, group="Reward",
         label="Penalty per step off the line or not progressing"),
    dict(name="respawn_penalty", type="float", default=5.0, min=0.0, max=100.0, step=0.5, group="Reward",
         label="Penalty when a respawn or give-up is forced"),
    dict(name="finish_bonus", type="float", default=50.0, min=0.0, max=500.0, step=1.0, group="Reward",
         label="Bonus for finishing the track"),
    dict(name="max_mistake_duration", type="float", default=4.0, min=0.5, max=30.0, step=0.5, group="Episode",
         label="Seconds of mistake before a respawn is forced"),
    dict(name="exploration", type="choice", default="cycle", choices=["cycle", "epsilon", "greedy"], group="Exploration",
         label="cycle = upstream schedule per episode, epsilon = fixed epsilon-greedy, greedy = best action only"),
    dict(name="epsilon", type="float", default=0.1, min=0.0, max=1.0, step=0.01, group="Exploration",
         label="Epsilon when exploration = epsilon"),
    dict(name="lr_scale", type="float", default=1.0, min=0.01, max=10.0, step=0.05, group="Learner",
         label="Learning rate multiplier applied to the schedule"),
    dict(name="batch_size", type="int", default=32, min=8, max=256, step=8, group="Learner",
         label="Learner batch size"),
]
DEFAULTS = {p["name"]: p["default"] for p in SCHEMA}
_BY_NAME = {p["name"]: p for p in SCHEMA}


def _coerce(name, value):
    spec = _BY_NAME[name]
    try:
        if spec["type"] == "bool":
            return value if isinstance(value, bool) else str(value).lower() in ("1", "true", "on", "yes")
        if spec["type"] == "choice":
            value = str(value)
            return value if value in spec["choices"] else spec["default"]
        value = int(float(value)) if spec["type"] == "int" else float(value)
        if value != value:  # NaN
            return spec["default"]
        return min(spec["max"], max(spec["min"], value))
    except (TypeError, ValueError):  # hand-edited file with a null / list / text: keep the default
        return spec["default"]


class TunableParams:
    def __init__(self, path, overrides=None):
        self.path = Path(path)
        self.values = dict(DEFAULTS)
        self._mtime = None
        self._dirty = False
        if self.path.exists():
            self._load()
        if overrides:
            self.values.update({k: _coerce(k, v) for k, v in overrides.items() if k in _BY_NAME})
        if overrides or not self.path.exists():
            self._write()  # otherwise keep the file as is: another process may have edited it meanwhile

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            self.values.update({k: _coerce(k, v) for k, v in data.items() if k in _BY_NAME})
        except (OSError, ValueError):
            return  # half-written file: keep the current values, the next poll retries
        self._mtime = self.path.stat().st_mtime

    def _write(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.values, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
        self._mtime = self.path.stat().st_mtime

    def poll(self):
        "Reload the file if it changed since the last poll; True when the values changed (or were updated locally)."
        changed, self._dirty = self._dirty, False
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return changed
        if mtime != self._mtime:
            before = dict(self.values)
            self._load()
            changed = changed or self.values != before
        return changed

    def update(self, **kwargs):
        self.values.update({k: _coerce(k, v) for k, v in kwargs.items() if k in _BY_NAME})
        self._write()
        self._dirty = True  # the file mtime is now our own: flag the change for the owner's next poll()
        return dict(self.values)

    def __getitem__(self, name):
        return self.values[name]

    def as_dict(self):
        return dict(self.values)
