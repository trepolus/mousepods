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


if __name__ == "__main__":
    unittest.main()
