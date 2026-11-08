# SPDX-License-Identifier: Apache-2.0
"""macOS motion source: wire parsing, unit conversion, and the UDP source with a fake helper."""
import json
import math
import os
import socket
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import airpods_mouse_controller as m  # noqa: E402
import macos_motion as mm  # noqa: E402

SAMPLE = {"type": "sample", "t": 10622.5, "rate": [0.5, -1.25, 2.0], "gravity": [0.0, -0.25, -0.968],
          "accel": [0.01, 0.0, -0.02], "quat": [0.9, 0.1, -0.3, 0.3]}


def wire(obj):
    return json.dumps(obj).encode()


def with_field(**changes):
    return {**SAMPLE, **changes}


class ParseDatagramTests(unittest.TestCase):
    def test_sample_keeps_coremotion_values(self):
        s = mm.parse_datagram(wire(SAMPLE))
        self.assertEqual(s, mm.MotionSample(10622.5, (0.5, -1.25, 2.0), (0.0, -0.25, -0.968),
                                            (0.01, 0.0, -0.02), (0.9, 0.1, -0.3, 0.3)))

    def test_every_status_name_is_understood(self):
        for name in ("connected", "disconnected", "unavailable", "denied"):
            self.assertEqual(mm.parse_datagram(wire({"type": "status", "status": name})),
                             mm.HeadphoneStatus(name), name)

    def test_hotkey_commands_are_understood(self):
        for name in ("recenter", "toggle", "scroll", "mode"):
            self.assertEqual(mm.parse_datagram(wire({"type": "command", "command": name})),
                             mm.HotkeyCommand(name), name)

    def test_hotkey_commands_are_ones_the_controller_accepts(self):
        accepted = {cmd for _, _, _, cmd in m.HOTKEYS}
        self.assertEqual({c.value for c in mm.HotkeyCommand}, accepted)

    def test_stem_presses_are_understood(self):
        for name in ("single", "double", "triple"):
            self.assertEqual(mm.parse_datagram(wire({"type": "stem", "press": name})), mm.StemPress(name), name)

    def test_stem_presses_match_the_stem_config(self):
        self.assertLessEqual({p.value for p in mm.StemPress}, set(m.DEFAULTS["stem"]))

    def test_hand_events_are_understood(self):
        cases = [
            ({"type": "hand", "event": "down", "finger": "index"}, mm.PinchDown(mm.Finger.INDEX)),
            ({"type": "hand", "event": "up", "finger": "middle"}, mm.PinchUp(mm.Finger.MIDDLE)),
            ({"type": "hand", "event": "fist"}, mm.FIST),
        ]
        for obj, want in cases:
            self.assertEqual(mm.parse_datagram(wire(obj)), want, obj)

    def test_hand_gestures_map_to_mouse_actions(self):
        cases = [
            ("index pinch holds the left button", mm.PinchDown(mm.Finger.INDEX), ("press", "left")),
            ("opening it releases", mm.PinchUp(mm.Finger.INDEX), ("release", "left")),
            ("middle pinch right-clicks", mm.PinchDown(mm.Finger.MIDDLE), ("command", "right_click")),
            ("middle release does nothing", mm.PinchUp(mm.Finger.MIDDLE), None),
            ("ring pinch toggles scroll", mm.PinchDown(mm.Finger.RING), ("command", "toggle_scroll")),
            ("fist pauses", mm.FIST, ("command", "pause")),
        ]
        for name, event, want in cases:
            self.assertEqual(mm.hand_action(event), want, name)

    def test_malformed_datagrams_are_dropped(self):
        cases = {
            "not json": b"{nope",
            "not utf-8": b"\xff\xfe",
            "json list": wire([1, 2]),
            "unknown type": wire({"type": "battery"}),
            "unknown status": wire({"type": "status", "status": "sleeping"}),
            "unknown command": wire({"type": "command", "command": "quit"}),
            "unknown stem press": wire({"type": "stem", "press": "long"}),
            "pinch without finger": wire({"type": "hand", "event": "down"}),
            "pinch with unknown finger": wire({"type": "hand", "event": "down", "finger": "little"}),
            "unknown hand event": wire({"type": "hand", "event": "wave"}),
            "missing gravity": wire({k: v for k, v in SAMPLE.items() if k != "gravity"}),
            "short rate": wire(with_field(rate=[1.0, 2.0])),
            "three-part quaternion": wire(with_field(quat=[1.0, 0.0, 0.0])),
            "string in vector": wire(with_field(accel=[0.0, "x", 0.0])),
            "boolean in vector": wire(with_field(accel=[0.0, True, 0.0])),
            "non-finite value": b'{"type":"sample","t":1,"rate":[NaN,0,0],"gravity":[0,0,-1],'
                                b'"accel":[0,0,0],"quat":[1,0,0,0]}',
            "missing timestamp": wire({k: v for k, v in SAMPLE.items() if k != "t"}),
            "text timestamp": wire(with_field(t="now")),
        }
        for name, data in cases.items():
            self.assertIsNone(mm.parse_datagram(data), name)

    def test_datagram_from_swift_encoder_parses(self):
        # Exact bytes from the Swift encoder (sorted keys, no spaces), as sent by the helper.
        data = (b'{"accel":[0.01,0,-0.02],"gravity":[0,-0.25,-0.968],"quat":[0.9,0.1,-0.3,0.3],'
                b'"rate":[0.5,-1.25,2],"t":10622.5,"type":"sample"}')
        self.assertEqual(mm.parse_datagram(data), mm.parse_datagram(wire(SAMPLE)))


class EngineUnitsTests(unittest.TestCase):
    def test_coremotion_units_become_raw_airpods_units(self):
        e = mm.to_engine(mm.parse_datagram(wire(SAMPLE)))
        self.assertEqual(e.ts_ns, 10622500000000)
        for got, want in zip(e.w_dps, (28.6479, -71.6197, 114.5916)):
            self.assertAlmostEqual(got, want, places=3)
        self.assertEqual(e.g, (0.0, -250.0, -968.0))
        for got, want in zip(e.a_ms2, (0.0981, 0.0, -0.1962)):
            self.assertAlmostEqual(got, want, places=4)

    def test_attitude_round_trips_through_quat_from_att(self):
        # No identity case: quat_from_att rejects a near-zero vector part as invalid data.
        cases = {
            "turned head": (0.9, 0.1, -0.3, 0.3),
            "negative w is the same rotation": (-0.9, -0.1, 0.3, -0.3),
            "unnormalised input": (1.8, 0.2, -0.6, 0.6),
        }
        for name, quat in cases.items():
            n = math.sqrt(sum(c * c for c in quat))
            want = tuple(c / n * (1 if quat[0] >= 0 else -1) for c in quat)
            got = m.quat_from_att(mm.attitude_q15(quat))
            self.assertIsNotNone(got, name)
            for g, w in zip(got, want):
                self.assertAlmostEqual(g, w, places=3, msg=name)


class NowPlayingSyncTests(unittest.TestCase):
    def test_claim_follows_mouse_state_and_is_refreshed(self):
        sync = mm.NowPlayingSync(refresh_s=2.0)
        steps = [
            ("first state is always sent", True, 0.0, True),
            ("unchanged within refresh is quiet", True, 1.0, None),
            ("pause releases at once", False, 1.5, False),
            ("unchanged release is quiet", False, 3.0, None),
            ("release is repeated after refresh", False, 3.6, False),
            ("resume claims at once", True, 3.7, True),
        ]
        for name, want, now, expected in steps:
            self.assertEqual(sync.update(want, now), expected, name)


class MacMotionSourceTests(unittest.TestCase):
    def setUp(self):
        self.app_dir = tempfile.mkdtemp()
        self.launched = []
        self.source = mm.MacMotionSource(app_path=self.app_dir,
                                         launcher=lambda cmd, check: self.launched.append(cmd))

    def tearDown(self):
        self.source.close()
        os.rmdir(self.app_dir)

    def send_from_helper(self, data):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(data, ("127.0.0.1", self.source.port))

    def test_helper_is_told_our_port_and_pid(self):
        self.source.start()
        self.assertEqual(self.launched, [["open", "-g", "-n", self.app_dir, "--args",
                                          "--port", str(self.source.port), "--parent-pid", str(os.getpid())]])

    def test_missing_helper_app_says_how_to_build_it(self):
        source = mm.MacMotionSource(app_path=os.path.join(self.app_dir, "missing.app"),
                                    launcher=lambda cmd, check: self.fail("must not launch"))
        try:
            with self.assertRaisesRegex(FileNotFoundError, "macos/build.sh"):
                source.start()
        finally:
            source.close()

    def test_control_reply_goes_to_the_helper_address(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as helper:
            helper.bind(("127.0.0.1", 0))
            helper.settimeout(2)
            self.assertFalse(self.source.send_control(now_playing=True), "no helper heard yet")
            helper.sendto(wire({"type": "status", "status": "connected"}), ("127.0.0.1", self.source.port))
            self.source.receive()
            self.assertTrue(self.source.send_control(now_playing=True))
            self.assertEqual(json.loads(helper.recv(512)), {"type": "control", "now_playing": True})
            self.assertTrue(self.source.send_control(camera=False))
            self.assertEqual(json.loads(helper.recv(512)), {"type": "control", "camera": False})

    def test_samples_and_status_arrive_over_udp(self):
        self.send_from_helper(wire({"type": "status", "status": "connected"}))
        self.send_from_helper(wire(SAMPLE))
        self.send_from_helper(b"garbage")
        self.assertEqual(self.source.receive(), mm.HeadphoneStatus.CONNECTED)
        self.assertEqual(self.source.receive().t, 10622.5)
        self.assertIsNone(self.source.receive())


CAPTURE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "captures",
                       "coremotion_guided.json")


class CoreMotionReplayTests(unittest.TestCase):
    """Guided capture from AirPods Pro 2 through CoreMotion (macOS 15), replayed through the real engine.

    Routine: still, turn (left first), still, nod (down first), still, tilt (left shoulder first), still.
    """

    @classmethod
    def setUpClass(cls):
        with open(CAPTURE) as f:
            capture = json.load(f)
        engine = m.MotionEngine(m.DEFAULTS["bias"], mm.DEFAULT_PROFILE)
        cls.cues = [cue for cue, _ in capture["routine"]]
        cls.rates = {i: [] for i in range(len(cls.cues))}
        last = None
        for event in capture["events"]:
            sample = mm.parse_datagram(json.dumps(event["msg"]).encode())
            if not isinstance(sample, mm.MotionSample):
                continue
            e = mm.to_engine(sample)
            dt = (e.ts_ns - last) / 1e9 if last else 0.04
            last = e.ts_ns
            cls.rates[event["cue"]].append(engine.step(e.w_dps, e.g, dt))

    def rms(self, cue):
        rows = self.rates[self.cues.index(cue)]
        return [math.sqrt(sum(r[k] ** 2 for r in rows) / len(rows)) for k in range(3)]

    def first_big(self, cue, axis):
        return next(r[axis] for r in self.rates[self.cues.index(cue)] if abs(r[axis]) > 20)

    def test_each_head_movement_lands_on_its_own_axis(self):
        yaw, pitch, roll = self.rms("turn left-right-left-right, slowly")
        self.assertGreater(yaw, 3 * max(pitch, roll), "turn")
        yaw, pitch, roll = self.rms("nod down-up-down-up, slowly")
        self.assertGreater(pitch, 3 * max(yaw, roll), "nod")
        # Tilting a head pitched forward partly turns it around the vertical, so yaw takes a share.
        yaw, pitch, roll = self.rms("tilt ear to left shoulder, then right, twice")
        self.assertGreater(roll, 2 * pitch, "tilt")
        self.assertGreater(roll, 15, "tilt")

    def test_directions_follow_the_calibration_convention(self):
        # profile_from_calibration: left = negative yaw, up = positive pitch, right = positive roll.
        self.assertLess(self.first_big("turn left-right-left-right, slowly", 0), 0, "left turn")
        self.assertLess(self.first_big("nod down-up-down-up, slowly", 1), 0, "nod down")
        self.assertLess(self.first_big("tilt ear to left shoulder, then right, twice", 2), 0, "tilt left")

    def test_holding_still_stays_quiet(self):
        for name in ("hold still, look straight ahead", "hold still"):
            self.assertLess(max(self.rms(name)), 12, name)


def replay_through_controller(**cfg_over):
    """Feed the guided capture through a real Controller (mouse on, fake pointer); clicks per cue."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from test_engine import FakePointer
    cfg = m.load_config("/nonexistent.json")
    cfg.update(notifications=False, mouse_paused=False, **cfg_over)
    ptr = FakePointer()
    ctl = m.Controller(cfg, ptr)
    ctl.set_device(mm.DEVICE_ID)
    ctl.set_place("ear")
    with open(CAPTURE) as f:
        capture = json.load(f)
    clicks = {cue: [] for cue, _ in capture["routine"]}
    for event in capture["events"]:
        sample = mm.parse_datagram(json.dumps(event["msg"]).encode())
        if not isinstance(sample, mm.MotionSample):
            continue
        e = mm.to_engine(sample)
        now = event["t_recv"] + 100.0
        before = len(ptr.clicks)
        ctl.on_sample(e.ts_ns, e.w_dps, e.g, e.a_ms2, e.att_q15, now)
        ctl.render(now)
        clicks[capture["routine"][event["cue"]][0]].extend(ptr.clicks[before:])
    return clicks


class CoreMotionClickReplayTests(unittest.TestCase):
    """Repo click features on the 25 Hz CoreMotion stream, replayed from the guided capture."""

    def test_head_tilt_click_never_fires_while_turning_nodding_or_still(self):
        # The capture's tilts are slow (about 1 s each), not the quick click gesture, so clicks there
        # are allowed but not required. A capture with quick tilts can prove the positive case.
        clicks = replay_through_controller(roll_click={**m.DEFAULTS["roll_click"], "enabled": True})
        clicks.pop("tilt ear to left shoulder, then right, twice")
        self.assertEqual({cue: c for cue, c in clicks.items() if c}, {})

    def test_dwell_click_fires_once_per_pause_after_moving(self):
        clicks = replay_through_controller(dwell_click={**m.DEFAULTS["dwell_click"], "enabled": True})
        # Three "hold still" phases follow a movement (turn, nod, tilt); the first one follows nothing.
        self.assertEqual(clicks.pop("hold still"), ["left", "left", "left"])
        self.assertEqual({cue: c for cue, c in clicks.items() if c}, {}, "no clicks while moving")

    def test_no_clicks_when_click_features_are_off(self):
        clicks = replay_through_controller()
        self.assertEqual({cue: c for cue, c in clicks.items() if c}, {})


class GuidedRecordTests(unittest.TestCase):
    def test_capture_tags_each_datagram_with_its_cue(self):
        app_dir = tempfile.mkdtemp()
        out_path = os.path.join(app_dir, "capture.json")

        def fake_helper(cmd, check):
            port = int(cmd[cmd.index("--port") + 1])
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.sendto(wire({"type": "status", "status": "connected"}), ("127.0.0.1", port))
                s.sendto(wire(SAMPLE), ("127.0.0.1", port))
                s.sendto(b"not json", ("127.0.0.1", port))

        source = mm.MacMotionSource(app_path=app_dir, launcher=fake_helper)
        lines = []
        ticks = iter(i * 0.01 for i in range(10_000))   # own clock: other tests swap time.monotonic
        mm.record(out_path, routine=(("hold still", 0.2), ("turn", 0.05)), source=source,
                  clock=lambda: next(ticks), out=lines.append)
        with open(out_path) as f:
            saved = json.load(f)
        os.remove(out_path)
        os.rmdir(app_dir)
        self.assertEqual(saved["routine"], [["hold still", 0.2], ["turn", 0.05]])
        self.assertEqual([(e["cue"], e["msg"]["type"]) for e in saved["events"]], [(0, "status"), (0, "sample")])
        self.assertEqual([line for line in lines if line.startswith(">>> ") and "s)" in line],
                         [">>> hold still (0.2 s)", ">>> turn (0.05 s)"])
        self.assertIn("1 samples saved", lines[-1])


if __name__ == "__main__":
    unittest.main()
