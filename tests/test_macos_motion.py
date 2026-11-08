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

    def test_malformed_datagrams_are_dropped(self):
        cases = {
            "not json": b"{nope",
            "not utf-8": b"\xff\xfe",
            "json list": wire([1, 2]),
            "unknown type": wire({"type": "battery"}),
            "unknown status": wire({"type": "status", "status": "sleeping"}),
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
