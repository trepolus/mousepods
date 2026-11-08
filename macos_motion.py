# SPDX-License-Identifier: Apache-2.0
"""macOS motion source: AirPods head tracking through CoreMotion, via the helper app in macos/.

macOS keeps the AirPods' control channel to itself, so the raw L2CAP path of the Linux build is not
available. Instead the small Swift helper (macos/build/MousePodsMotion.app) reads CMHeadphoneMotionManager
(about 25 Hz) and sends one JSON object per UDP datagram to 127.0.0.1. This module receives them and
converts them to the units the motion engine uses for the raw AirPods stream.

Wire format (frozen, mirrored by macos/Sources/MotionWire):
  {"type": "sample", "t": s, "rate": [rad/s]*3, "gravity": [g]*3, "accel": [g]*3, "quat": [w, x, y, z]}
  {"type": "status", "status": "connected" | "disconnected" | "unavailable" | "denied"}
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
GRAVITY_UNITS_PER_G = 1000.0      # raw AirPods stream: ~1000 = 1 g (see parse_block)
STANDARD_GRAVITY = 9.81           # m/s² per g, as in parse_accel


class HeadphoneStatus(enum.Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    UNAVAILABLE = "unavailable"
    DENIED = "denied"


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
    """Datagram bytes -> MotionSample | HeadphoneStatus, or None for anything malformed or unknown."""
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
        """Read one datagram: MotionSample | HeadphoneStatus | None (malformed, dropped)."""
        data = self.sock.recv(4096)
        return parse_datagram(data)

    def close(self):
        self.sock.close()
