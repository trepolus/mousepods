# SPDX-License-Identifier: Apache-2.0
"""macOS motion source: AirPods head tracking through CoreMotion, via the helper app in macos/.

macOS keeps the AirPods' control channel to itself, so the raw L2CAP path of the Linux build is not
available. Instead the small Swift helper (macos/build/MousePodsMotion.app) reads CMHeadphoneMotionManager
(about 25 Hz) and sends one JSON object per UDP datagram to 127.0.0.1. This module receives them and
converts them to the units the motion engine uses for the raw AirPods stream.

Wire format (frozen, mirrored by macos/Sources/MotionWire):
  {"type": "sample", "t": s, "rate": [rad/s]*3, "gravity": [g]*3, "accel": [g]*3, "quat": [w, x, y, z]}
  {"type": "status", "status": "connected" | "disconnected" | "unavailable" | "denied"}
  {"type": "command", "command": "recenter" | "toggle" | "scroll" | "mode"}   (global shortcuts)
"""
import enum
import json
import math
import os
import socket
import subprocess
from dataclasses import dataclass

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_APP = os.path.join(HERE, "macos", "build", "MousePodsMotion.app")
DEVICE_ID = "coremotion"          # Controller.set_device id; profiles are stored as coremotion_<source>
# CoreMotion reports every model in one head frame: x = ear to ear (nod), y = forward (tilt), z = up (turn).
# Signs follow profile_from_calibration (left = negative yaw, up = positive pitch, right = positive roll);
# derived from captures/coremotion_guided.json and guarded by tests/test_macos_motion.py.
DEFAULT_PROFILE = {"yaw_sign": 1, "lat": [1.0, 0.0, 0.0], "pitch_sign": 1, "roll_sign": -1}
GRAVITY_UNITS_PER_G = 1000.0      # raw AirPods stream: ~1000 = 1 g (see parse_block)
STANDARD_GRAVITY = 9.81           # m/s² per g, as in parse_accel


class HeadphoneStatus(enum.Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    UNAVAILABLE = "unavailable"
    DENIED = "denied"


class HotkeyCommand(enum.Enum):
    """System-wide shortcuts registered by the helper (Control+Option+C/P/S/M); values are --send commands."""
    RECENTER = "recenter"
    TOGGLE = "toggle"
    SCROLL = "scroll"
    MODE = "mode"


@dataclass(frozen=True)
class MotionSample:
    """One CoreMotion reading in CoreMotion units (seconds, rad/s, g, unit quaternion w, x, y, z)."""
    t: float
    rate: tuple
    gravity: tuple
    accel: tuple
    quat: tuple


@dataclass(frozen=True)
class EngineSample:
    """The same reading in the units Controller.on_sample takes from the raw AirPods stream."""
    ts_ns: int
    w_dps: tuple
    g: tuple
    a_ms2: tuple
    att_q15: tuple


def _vector(value, size):
    if not isinstance(value, list) or len(value) != size:
        return None
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in value):
        return None
    return tuple(float(v) for v in value)


def parse_datagram(data):
    """Datagram bytes -> MotionSample | HeadphoneStatus | HotkeyCommand, or None if malformed or unknown."""
    try:
        obj = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(obj, dict):
        return None
    kind = obj.get("type")
    if kind == "status":
        try:
            return HeadphoneStatus(obj.get("status"))
        except ValueError:
            return None
    if kind == "command":
        try:
            return HotkeyCommand(obj.get("command"))
        except ValueError:
            return None
    if kind == "sample":
        t = obj.get("t")
        if not isinstance(t, (int, float)) or isinstance(t, bool) or not math.isfinite(t):
            return None
        rate, gravity, accel = (_vector(obj.get(k), 3) for k in ("rate", "gravity", "accel"))
        quat = _vector(obj.get("quat"), 4)
        if None in (rate, gravity, accel, quat):
            return None
        return MotionSample(float(t), rate, gravity, accel, quat)
    return None


def attitude_q15(quat):
    """Unit quaternion (w, x, y, z) -> vector part in Q15 with w >= 0, the AirPods' attitude format.

    q and -q are the same rotation; quat_from_att assumes w >= 0, so flip the sign when w < 0.
    """
    w, x, y, z = quat
    n = math.sqrt(w * w + x * x + y * y + z * z) or 1.0
    s = (-1.0 if w < 0 else 1.0) / n
    return tuple(max(-32768, min(32767, round(c * s * 32768.0))) for c in (x, y, z))


def to_engine(sample):
    """CoreMotion units -> engine units (see Controller.on_sample)."""
    deg = 180.0 / math.pi
    return EngineSample(
        ts_ns=int(round(sample.t * 1e9)),
        w_dps=tuple(v * deg for v in sample.rate),
        g=tuple(v * GRAVITY_UNITS_PER_G for v in sample.gravity),
        a_ms2=tuple(v * STANDARD_GRAVITY for v in sample.accel),
        att_q15=attitude_q15(sample.quat),
    )


class MacMotionSource:
    """Owns the UDP socket and the helper app. `sock` is select()-able; read with `receive()`.

    The socket binds an ephemeral port on 127.0.0.1, so two controllers never collide. The helper gets
    our pid and exits within about a second after this process ends, crash included.
    """

    def __init__(self, app_path=None, launcher=subprocess.run):
        self.app_path = app_path or os.environ.get("MOUSEPODS_MOTION_APP", DEFAULT_APP)
        self._launcher = launcher
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]

    def launch_command(self):
        # -g: do not bring it to the front, -n: a fresh instance with our arguments
        return ["open", "-g", "-n", self.app_path, "--args",
                "--port", str(self.port), "--parent-pid", str(os.getpid())]

    def start(self):
        """Start the helper. Raises FileNotFoundError when it has not been built yet."""
        if not os.path.isdir(self.app_path):
            raise FileNotFoundError(
                f"{self.app_path} is missing: build it with macos/build.sh")
        self._launcher(self.launch_command(), check=True)

    def receive(self):
        """Read one datagram: MotionSample | HeadphoneStatus | HotkeyCommand | None (malformed, dropped)."""
        data = self.sock.recv(4096)
        return parse_datagram(data)

    def close(self):
        self.sock.close()


# --------------------------------------------------------------------------- guided capture
# Each step: (cue shown to the wearer, seconds). Used to learn the CoreMotion axis frame.
GUIDED_ROUTINE = (
    ("hold still, look straight ahead", 8),
    ("turn left-right-left-right, slowly", 8),
    ("hold still", 4),
    ("nod down-up-down-up, slowly", 8),
    ("hold still", 4),
    ("tilt ear to left shoulder, then right, twice", 8),
    ("hold still", 4),
)


def record(path, routine=GUIDED_ROUTINE, source=None, clock=None, out=print):
    """Run the guided routine and save every helper datagram, tagged with the active cue, as JSON.

    File: {"source": "coremotion", "routine": [[cue, s], ...],
           "events": [{"t_recv": s, "cue": i, "msg": <datagram object>}, ...]}
    """
    import select
    import time
    clock = clock or time.monotonic
    source = source or MacMotionSource()
    events = []
    try:
        source.start()
        out("Recording. Follow the cues; keep your shoulders still.")
        t0 = clock()
        for index, (cue, seconds) in enumerate(routine):
            out(f">>> {cue} ({seconds} s)")
            end = clock() + seconds
            while (left := end - clock()) > 0:
                r, _, _ = select.select([source.sock], [], [], left)
                if r:
                    data = source.sock.recv(4096)
                    try:
                        msg = json.loads(data)
                    except ValueError:
                        continue
                    events.append({"t_recv": round(clock() - t0, 4), "cue": index, "msg": msg})
    finally:
        source.close()
    with open(path, "w") as f:
        json.dump({"source": "coremotion", "routine": [list(step) for step in routine], "events": events}, f)
    samples = sum(1 for e in events if e["msg"].get("type") == "sample")
    out(f">>> done: {samples} samples saved to {path}")
    return events


def main(argv=None):
    import argparse
    import time
    ap = argparse.ArgumentParser(
        prog="python -m macos_motion",
        description="macOS CoreMotion motion source tools. Needs the helper app built with macos/build.sh.")
    sub = ap.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record", help="guided ~44 s capture of the raw CoreMotion stream to a JSON file")
    rec.add_argument("path", nargs="?", default=os.path.join(
        HERE, "captures", "private", time.strftime("coremotion_guided_%Y%m%d_%H%M%S.json")),
        help="output file (default: captures/private/coremotion_guided_<time>.json)")
    args = ap.parse_args(argv)
    if args.command == "record":
        os.makedirs(os.path.dirname(os.path.abspath(args.path)), exist_ok=True)
        record(args.path)


if __name__ == "__main__":
    main()
