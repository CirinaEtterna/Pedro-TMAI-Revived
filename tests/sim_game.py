"""A fake Trackmania for smoke tests: same interface as tmenv's Game, no game needed.

The car follows the reference ghost line of the loaded map with toy kinematics (accelerate / brake /
steer move it along or away from the line), and produces the 88 telemetry fields of the AITool plugin.
"""
import threading
from time import sleep, time

import numpy as np
import torch

from tmenv.gbx import map_from_url

UP = np.array([0.0, 1.0, 0.0])


class SimGame:
    def __init__(self, *args, hz=150, **kwargs):
        self.hz = hz
        self.lock = threading.Lock()
        self.inputs = dict(accelerate=False, brake=False, steer=0.0)
        self.telemetry = self.previous_telemetry = {}
        self.path = None
        self.running = True
        self.passive = False  # master-learn smoke test: a scripted "user" drives along the line
        self._finish_time = 0.0
        threading.Thread(target=self._loop, daemon=True, name="sim-game").start()

    # Game interface
    def load_map(self, url, timeout=30):
        ghost = map_from_url(url, True)["ghosts"]["wr"]
        positions = np.array([s["position"] for s in ghost["samples"]], dtype=np.float64)
        seg = np.linalg.norm(np.diff(positions, axis=0), axis=1)
        keep = np.concatenate([[True], seg > 1e-3])
        self.path = positions[keep]
        self.cum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(self.path, axis=0), axis=1))])
        racetimes = np.array([s["racetime"] for s in ghost["samples"]])[keep]
        self.cp_s = [self.cum[min(np.searchsorted(racetimes, t), len(self.cum) - 1)] for t in ghost["checkpoints"]]
        self.give_up()

    def act(self, accelerate, brake, steer, check_socket=True):
        with self.lock:
            self.inputs = dict(accelerate=bool(accelerate), brake=bool(brake), steer=float(steer))

    def give_up(self, wait_go=False, timeout=5, retry=5):
        with self.lock:
            self.s, self.v, self.d, self.cp = 0.0, 0.0, 0.0, 0
            self.start, self.finished = time(), False
            self.cp_state = (0.0, 0.0)
        sleep(0.05)

    def respawn(self, launched=True, wait_go=False, **kwargs):
        with self.lock:
            self.s, cp_v = self.cp_state
            self.v, self.d = (cp_v if launched else 0.0), 0.0
        sleep(0.05)

    def toggle_interface(self):
        pass

    def wait_user_start(self, stop_check=None):
        "Same contract as tmenv.game.Game.wait_user_start (SimGame does not inherit from Game)."
        while 0 < self.telemetry.get("racetime", 1) and not (self.telemetry.get("racetime", 1) <= 1500 and self.telemetry.get("speed", 0) < 1):
            if stop_check is not None:
                stop_check()
            sleep(0.02)
        while self.telemetry.get("racetime", 1) <= 0:
            if stop_check is not None:
                stop_check()
            sleep(0.01)

    def save_ghost(self, url, header):
        pass

    def capture_tensor(self):
        frame = torch.zeros(3, 540, 960, dtype=torch.uint8)
        frame[0] = int(128 + max(-127, min(127, self.d * 10)))  # left/right offset visible in the frame
        frame[1, :, : int(960 * min(1.0, self.v / 80))] = 255
        return frame

    def recover(self):
        self.give_up()

    def close(self):
        self.running = False

    # Simulation
    def _point(self, s):
        s = min(max(s, 0.0), self.cum[-1] - 1e-6)
        i = int(np.searchsorted(self.cum, s, side="right") - 1)
        t = (s - self.cum[i]) / (self.cum[i + 1] - self.cum[i])
        forward = self.path[i + 1] - self.path[i]
        return self.path[i] + t * forward, forward / np.linalg.norm(forward)

    def _loop(self):
        dt = 1.0 / self.hz
        while self.running:
            sleep(dt)
            if self.path is None:
                continue
            with self.lock:
                if self.passive:
                    steer = -1.0 if 1.0 < self.d else (1.0 if self.d < -1.0 else 0.0)
                    self.inputs = dict(accelerate=self.v < 60.0, brake=False, steer=steer)
                    if self.finished and 1.0 < time() - self._finish_time:  # the "user" restarts
                        self.s, self.v, self.d, self.cp = 0.0, 0.0, 0.0, 0
                        self.start, self.finished, self.cp_state = time(), False, (0.0, 0.0)
                a = self.inputs
                if not self.finished:
                    self.v += (14.0 * a["accelerate"] - 30.0 * a["brake"] - 1.5) * dt
                    self.v = min(max(self.v, 0.0), 90.0)
                    self.d += a["steer"] * self.v * 0.05 * dt + 0.15 * np.sin(self.s / 25.0) * self.v * dt * 0.05
                    grip = 1.0 if abs(self.d) < 8 else 0.3  # off the line is slow
                    self.s += self.v * grip * dt
                    while self.cp < len(self.cp_s) and self.cp_s[self.cp] <= self.s:
                        self.cp += 1
                        self.cp_state = (self.s, self.v)
                    if not self.finished and self.cp >= len(self.cp_s):
                        self.finished, self._finish_time = True, time()
                center, forward = self._point(self.s)
                left = np.cross(UP, forward)
                left /= np.linalg.norm(left)
                up = np.cross(forward, left)
                position = center + self.d * left
                racetime = int((time() - self.start) * 1000)
                t = self._telemetry(position, forward * self.v, forward, left, up, racetime, a)
            self.previous_telemetry, self.telemetry = self.telemetry, t

    def _telemetry(self, position, velocity, forward, left, up, racetime, a):
        t = dict(
            finished=self.finished, ui_sequence=4 if self.finished else 1, landmark_index=self.cp,
            standing_landmark_index=self.cp, racetime=racetime, position=position.tolist(),
            velocity=velocity.tolist(), forward=forward.tolist(), left=left.tolist(), up=up.tolist(),
            steer=a["steer"], accelerate=float(a["accelerate"]), brake=a["brake"], distance=self.s,
            speed=self.v * 3.6, accel_coef=1.0, control_coef=1.0, gravity_coef=1.0, adherence_coef=1.0,
            upwardness=1.0, wheels_contact_count=4, wheels_skidding_count=0, flying_duration=0,
            skidding_duration=0, handicap_no_gas_duration=0, handicap_force_gas_duration=0,
            handicap_no_brakes_duration=0, handicap_no_steering_duration=0, handicap_no_grip_duration=0,
            reactor_boost_level=0, reactor_boost_type=0, reactor_inputs_x=False, is_ground_contact=True,
            is_reactor_ground_mode=False, is_wheels_burning=False, ground_dist=0.0, gear=min(5, 1 + int(self.v // 18)),
            engine_on=True, is_turbo=False, turbo_time=0.0, bullet_time_normed=0.0, simulation_time_coef=1.0,
            air_brake_normed=0.0, spoiler_open_normed=0.0, wings_open_normed=0.0, is_top_contact=False,
            wetness=0.0, water_immersion_coef=0.0, water_over_dist_normed=0.0, side_speed=0.0,
            rpm=min(11000.0, 2000 + self.v * 100), front_speed=self.v,
        )
        for w in ("fl", "fr", "rl", "rr"):
            t |= {f"{w}_wheel_steer_angle": a["steer"] * 0.3, f"{w}_wheel_rotation": self.s, f"{w}_wheel_damper_len": 0.1,
                  f"{w}_wheel_slip_coef": 0.0, f"{w}_wheel_dirt": 0.0, f"{w}_wheel_break_coef": 0.0,
                  f"{w}_wheel_tire_wear": 0.0, f"{w}_wheel_icing": 0.0, f"{w}_wheel_contact_material": 16}
        t["_updatetime"] = time()
        return t
