"""Windows backend for tmenv.

The original tmenv drives Trackmania inside wine prefixes on Linux (firejail sandbox, X11 window
capture, X11 key events and evdev virtual gamepads). This module provides the same `Game`
interface for a native Windows Trackmania running Openplanet + the AITool plugin:

* Trackmania is started by the user, or launched through Steam / Ubisoft Connect / an exe path,
* the AITool plugin connects to a fixed localhost port (its default, 20131),
* keys are injected with SendInput scan codes, *only* while Trackmania is the foreground window,
* frames are grabbed from the game window client area with mss,
* steering can optionally go through a virtual Xbox 360 pad (vgamepad + ViGEmBus) for analog values.
"""

__all__ = ['DEFAULT_PORT', 'STEAM_APP_ID', 'UBISOFT_LAUNCH_URL', 'SCANCODES', 'send_keys', 'release_all_keys',
           'find_game_windows', 'game_running', 'launch_game', 'TmWindow', 'VirtualGamepad', 'WinGame']

import atexit
import ctypes
import logging
import os
import subprocess
import threading
from ctypes import wintypes as wt
from pathlib import Path
from time import sleep, time

import mss
import numpy as np
import psutil
import torch

from .game import Game
from .socket import Socket

DEFAULT_PORT = 20131  # AITool plugin default "Socket port" setting
STEAM_APP_ID = 2225070
UBISOFT_LAUNCH_URL = "uplay://launch/5595/0"

user32 = ctypes.WinDLL("user32", use_last_error=True)

# Physical pixel coordinates for window rects and screen grabs
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per monitor v2
except (AttributeError, OSError):
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        user32.SetProcessDPIAware()

# %% SendInput keyboard
ULONG_PTR = ctypes.c_size_t
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = (wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wt.UINT

# X11 keysym names used by tmenv -> (set 1 scan code, extended key). Trackmania default keyboard binds:
# Up accelerate, Down brake, Left/Right steer, Delete give up, BackSpace respawn, Numpad * toggle interface.
SCANCODES = {
    "Up": (0x48, True), "Down": (0x50, True), "Left": (0x4B, True), "Right": (0x4D, True),
    "Delete": (0x53, True), "BackSpace": (0x0E, False), "Return": (0x1C, False),
    "KP_Multiply": (0x37, False), "Escape": (0x01, False), "Alt": (0x38, False), "g": (0x22, False),
}

_held_keys = set()
_held_lock = threading.Lock()


def send_keys(keys, up=False):
    "Press (or release) `keys` with a single SendInput call using hardware scan codes."
    keys = [keys] if isinstance(keys, str) else list(keys)
    if not keys:
        return
    inputs = (INPUT * len(keys))()
    for inp, key in zip(inputs, keys):
        code, extended = SCANCODES[key]
        flags = KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if extended else 0) | (KEYEVENTF_KEYUP if up else 0)
        inp.type = INPUT_KEYBOARD
        inp.u.ki = KEYBDINPUT(0, code, flags, 0, 0)
    sent = user32.SendInput(len(keys), inputs, ctypes.sizeof(INPUT))
    if sent != len(keys):
        logging.warning(f"SendInput injected {sent}/{len(keys)} key events (error {ctypes.get_last_error()})")
    with _held_lock:
        (_held_keys.difference_update if up else _held_keys.update)(keys)


@atexit.register
def release_all_keys():
    "Never leave a key held down at OS level (e.g. when training is interrupted mid-step)."
    with _held_lock:
        held = list(_held_keys)
    if held:
        send_keys(held, up=True)

# %% Windows and process helpers
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.EnumWindows.argtypes = (WNDENUMPROC, wt.LPARAM)
user32.GetWindowThreadProcessId.argtypes = (wt.HWND, ctypes.POINTER(wt.DWORD))
user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowLongW.argtypes = (wt.HWND, ctypes.c_int)
user32.GetWindowLongW.restype = wt.LONG
user32.SetWindowPos.argtypes = (wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT)
# 64 bit handles: declare HWND arguments, ctypes would otherwise convert them to 32 bit ints
for _fn in ("IsWindowVisible", "IsWindow", "IsIconic", "SetForegroundWindow", "GetWindowTextLengthW"):
    getattr(user32, _fn).argtypes = (wt.HWND,)
user32.GetWindowTextW.argtypes = (wt.HWND, wt.LPWSTR, ctypes.c_int)
user32.GetClientRect.argtypes = (wt.HWND, ctypes.POINTER(wt.RECT))
user32.ClientToScreen.argtypes = (wt.HWND, ctypes.POINTER(wt.POINT))
user32.ShowWindow.argtypes = (wt.HWND, ctypes.c_int)
user32.AdjustWindowRectEx.argtypes = (ctypes.POINTER(wt.RECT), wt.DWORD, wt.BOOL, wt.DWORD)
GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CAPTION = 0x00C00000
SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010
SW_RESTORE = 9


def _window_title(hwnd):
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _client_rect(hwnd):
    rect, origin = wt.RECT(), wt.POINT(0, 0)
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    return origin.x, origin.y, rect.right - rect.left, rect.bottom - rect.top


def find_game_windows(exe_name="Trackmania.exe"):
    "Visible top level windows owned by `exe_name`, largest first."
    windows = []

    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd) and _window_title(hwnd):
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                if psutil.Process(pid.value).name().lower() == exe_name.lower():
                    windows.append(hwnd)
            except psutil.Error:
                pass
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return sorted(windows, key=lambda h: _client_rect(h)[2] * _client_rect(h)[3], reverse=True)


def game_running(exe_name="Trackmania.exe"):
    return any((p.info["name"] or "").lower() == exe_name.lower() for p in psutil.process_iter(["name"]))


def launch_game(launch):
    """Start Trackmania: `launch` is "steam", "ubisoft", a path to Trackmania.exe or any command line."""
    if launch == "steam":
        os.startfile(f"steam://rungameid/{STEAM_APP_ID}")
    elif launch == "ubisoft":
        os.startfile(UBISOFT_LAUNCH_URL)
    elif Path(launch).exists():
        subprocess.Popen([str(launch)], cwd=str(Path(launch).parent))
    else:
        subprocess.Popen(launch, shell=True)
    logging.info(f"Launching Trackmania ({launch}) ...")

# %% Window: capture + keyboard
_capture_local = threading.local()


def _mss():
    # mss device contexts are thread bound on Windows
    if not hasattr(_capture_local, "sct"):
        _capture_local.sct = mss.mss()
    return _capture_local.sct


class TmWindow:
    keys = ("Up", "Down", "Left", "Right")

    def __init__(self, hwnd, steal_focus=True, tap_duration=0.03):
        self.hwnd, self.steal_focus, self.tap_duration = hwnd, steal_focus, tap_duration
        self.pressed = set()
        self.inputs_paused = False  # True while keys can't be delivered (game not focused)
        self._last_focus_warning = self._last_focus_attempt = 0.0

    @classmethod
    def wait(cls, exe_name="Trackmania.exe", stop_check=None, **kwargs):
        last_log = 0.0
        while not (windows := find_game_windows(exe_name)):
            if stop_check is not None:
                stop_check()
            if 15 < time() - last_log:
                logging.info(f"Waiting for the Trackmania window ({exe_name}) ...")
                last_log = time()
            sleep(1)
        logging.info(f"Found Trackmania window '{_window_title(windows[0])}' {_client_rect(windows[0])}")
        return cls(windows[0], **kwargs)

    # Window state
    def alive(self):
        return bool(user32.IsWindow(self.hwnd))

    def is_foreground(self):
        return user32.GetForegroundWindow() == self.hwnd

    def client_rect(self):
        return _client_rect(self.hwnd)

    def focus(self):
        if self.is_foreground():
            return True
        if user32.IsIconic(self.hwnd):
            user32.ShowWindow(self.hwnd, SW_RESTORE)
        # Only the foreground process may change the foreground window: an Alt tap lifts that lock
        send_keys("Alt")
        send_keys("Alt", up=True)
        user32.SetForegroundWindow(self.hwnd)
        sleep(0.1)
        return self.is_foreground()

    def ensure_focus(self):
        return self.is_foreground() or (self.steal_focus and self.focus())

    def set_position(self, x, y):
        user32.SetWindowPos(self.hwnd, None, x, y, 0, 0, SWP_NOZORDER | SWP_NOACTIVATE | 0x0001)  # SWP_NOSIZE

    def set_geometry(self, x, y, width, height):
        "Resize so the client area (the captured frame) is width x height. Only for windowed mode."
        style = user32.GetWindowLongW(self.hwnd, GWL_STYLE)
        if not style & WS_CAPTION:
            logging.warning(
                f"Trackmania is not in windowed mode: frames are captured at {self.client_rect()[2:]} "
                f"and downscaled. Use DISPLAY MODE: WINDOWED for a {width}x{height} capture.")
            return
        rect = wt.RECT(0, 0, width, height)
        user32.AdjustWindowRectEx(ctypes.byref(rect), style, False, user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE))
        user32.SetWindowPos(self.hwnd, None, x, y, rect.right - rect.left, rect.bottom - rect.top,
                            SWP_NOZORDER | SWP_NOACTIVATE)
        sleep(0.5)
        logging.info(f"Trackmania client area is now {self.client_rect()}")

    # Capture (BGR like the original X11 capture)
    def capture_raw(self):
        left, top, width, height = self.client_rect()
        if width <= 0 or height <= 0:
            if user32.IsIconic(self.hwnd):  # minimized: the capture needs the window on screen
                user32.ShowWindow(self.hwnd, SW_RESTORE)
                sleep(0.3)
                left, top, width, height = self.client_rect()
            if width <= 0 or height <= 0:
                raise RuntimeError("Trackmania window has no visible client area (minimized or exclusive "
                                   "fullscreen?): use DISPLAY MODE: WINDOWED and keep the game on screen")
        shot = _mss().grab({"left": left, "top": top, "width": width, "height": height})
        return shot.raw, width, height

    def capture_numpy_array(self):
        raw, width, height = self.capture_raw()
        return np.frombuffer(raw, dtype=np.uint8).reshape([height, width, 4])[:, :, :3]

    def capture_tensor(self):
        raw, width, height = self.capture_raw()
        return torch.frombuffer(raw, dtype=torch.uint8).view(height, width, 4)[:, :, :3].permute(2, 0, 1)

    def capture_image(self):
        from PIL import Image
        return Image.fromarray(self.capture_numpy_array()[:, :, ::-1].copy())

    # Keyboard
    def _can_send(self):
        if self.is_foreground():
            self.inputs_paused = False
            return True
        if self.pressed:
            send_keys(self.pressed, up=True)
            self.pressed = set()
        if self.steal_focus and 2 < time() - self._last_focus_attempt:
            self._last_focus_attempt = time()
            if self.focus():
                logging.info("Trackmania was not the foreground window: focus taken back.")
                self.inputs_paused = False
                return True
        self.inputs_paused = True
        if 10 < time() - self._last_focus_warning:
            logging.warning("Trackmania is not the foreground window: inputs are paused and these steps "
                            "are not learned from until it is focused.")
            self._last_focus_warning = time()
        return False

    def key_press(self, key):
        if self._can_send():
            send_keys(key)

    def key_release(self, key):
        send_keys(key, up=True)

    def key_tap(self, key):
        if not (self.ensure_focus() and self._can_send()):
            return
        send_keys(key)
        sleep(self.tap_duration)  # hold for a couple of frames so the game polls it
        send_keys(key, up=True)

    def act(self, accelerate, brake, steer):
        wanted = {k for k, on in zip(self.keys, (accelerate, brake, steer < 0.0, 0.0 < steer)) if on}
        if not self._can_send():
            return
        if release := self.pressed - wanted:
            send_keys(release, up=True)
        if press := wanted - self.pressed:
            send_keys(press)
        self.pressed = wanted

    def release_all(self):
        if self.pressed:
            send_keys(self.pressed, up=True)
            self.pressed = set()

    def give_up(self):
        self.release_all()
        self.key_tap("Delete")

    def respawn(self, launched=True):
        self.release_all()
        self.key_tap("BackSpace")
        if not launched:
            sleep(0.01)
            self.key_tap("BackSpace")

    def toggle_interface(self):
        self.key_tap("KP_Multiply")

# %% Optional analog steering
class VirtualGamepad:
    "Virtual Xbox 360 pad for analog steering (pip install vgamepad, requires the ViGEmBus driver)."

    def __init__(self):
        import vgamepad
        self.pad = vgamepad.VX360Gamepad()

    def act(self, accelerate, brake, steer):
        self.pad.left_joystick_float(x_value_float=float(steer), y_value_float=0.0)
        self.pad.update()

# %% Game
class WinGame(Game):
    def __init__(
        self,
        name,
        width,
        height,
        window_x=0,
        window_y=0,
        port=DEFAULT_PORT,
        launch=None,  # None (start Trackmania yourself), "steam", "ubisoft" or a path to Trackmania.exe
        analog_steer=False,  # steer with a virtual gamepad instead of the arrow keys
        resize_window=True,
        steal_focus=True,  # bring Trackmania to the foreground when an episode starts
        stop_check=None,  # callable raising when the collector is asked to stop (waits observe it)
    ):
        self.name, self.width, self.height = name, width, height
        self.stop_check = stop_check
        self.window_x, self.window_y = window_x, window_y
        self.port, self.launch = port, launch
        self.resize_window, self.steal_focus = resize_window, steal_focus
        self.gamepad = VirtualGamepad() if analog_steer else None
        self.window = None
        self.socket = self._listen()
        self.start_and_connect_game()

    def _listen(self, timeout=60):
        start_time = time()
        while True:
            try:
                return Socket(port=self.port)
            except OSError as e:
                if timeout < time() - start_time:
                    raise OSError(f"Port {self.port} is busy: is another training already running?") from e
                if self.stop_check is not None:
                    self.stop_check()
                sleep(1)

    def start_and_connect_game(self):
        if not game_running():
            if self.launch:
                launch_game(self.launch)
            else:
                logging.warning("Trackmania is not running: start it (with Openplanet) to continue.")
        self.window = TmWindow.wait(steal_focus=self.steal_focus, stop_check=self.stop_check)
        if self.resize_window:
            self.window.set_geometry(self.window_x, self.window_y, self.width, self.height)
        last_log = 0.0
        while not self.socket.connected:
            if self.stop_check is not None:
                self.stop_check()
            if 15 < time() - last_log:
                logging.info(
                    f"Waiting for the AITool Openplanet plugin to connect on 127.0.0.1:{self.port} "
                    "(Openplanet must be in Developer signature mode with AITool loaded) ...")
                last_log = time()
            sleep(0.5)
        logging.info("AITool plugin connected, telemetry is streaming.")
        self.window.ensure_focus()

    def recover(self):
        """Reconnect to the game (relaunching it when `launch` is set). To be used in the event of a crash."""
        self.act(False, False, 0, check_socket=False)
        self.socket.close()
        self.socket = self._listen()
        self.start_and_connect_game()

    def wait_focus(self):
        "Wait until Trackmania is the foreground window (taking focus when allowed) before sending a key tap."
        start, last_log = time(), 0.0
        while not self.window.ensure_focus():
            if not self.window.alive():
                raise RuntimeError("The Trackmania window is gone")  # recover() reconnects or relaunches
            if self.stop_check is not None:
                self.stop_check()
            if 10 < time() - last_log:
                logging.warning(f"Waiting for the Trackmania window to be focused ({time() - start:.0f}s)")
                last_log = time()
            sleep(0.5)

    def give_up(self, wait_go=False, timeout=5, retry=5):
        self.wait_focus()  # a give-up that can't be sent would end in a map reload
        return super().give_up(wait_go, timeout, retry)

    def respawn(self, launched=True, wait_go=False, timeout=2, retry=5, initial_wait=0.2):
        self.wait_focus()
        return super().respawn(launched, wait_go, timeout, retry, initial_wait)

    def act(self, accelerate, brake, steer, check_socket=True):
        assert not check_socket or self.socket.connected
        if self.passive:  # master-learn: the user drives, their inputs are never "paused"
            if self.window.pressed:
                self.window.release_all()
            self.window.inputs_paused = False
            return
        if self.gamepad is None:
            self.window.act(accelerate, brake, steer)
        else:
            self.window.act(accelerate, brake, 0)
            self.gamepad.act(False, False, steer)

    def load_map(self, url, timeout=30):
        self.wait_focus()
        super().load_map(url, timeout)

    def toggle_interface(self):
        self.wait_focus()
        super().toggle_interface()

    def close(self):
        if self.window is not None:
            self.window.release_all()
        self.socket.close()
