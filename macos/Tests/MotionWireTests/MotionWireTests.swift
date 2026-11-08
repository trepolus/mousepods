// SPDX-License-Identifier: Apache-2.0
import Foundation
import MotionWire
import Testing

private func decode(_ data: Data) throws -> [String: Any] {
    try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
}

@Suite("Wire encoding")
struct WireEncodingTests {
    let sample = MotionSample(
        timestamp: 10622.5,
        rotationRate: Vector3(x: 0.5, y: -1.25, z: 2),
        gravity: Vector3(x: 0, y: -0.25, z: -0.968),
        userAcceleration: Vector3(x: 0.01, y: 0, z: -0.02),
        attitude: Quaternion(w: 0.9, x: 0.1, y: -0.3, z: 0.3)
    )

    @Test("sample keeps every value under its wire name")
    func sampleFields() throws {
        let json = try decode(encodeLine(.sample(sample)))
        #expect(json["type"] as? String == "sample")
        #expect(json["t"] as? Double == 10622.5)
        #expect(json["rate"] as? [Double] == [0.5, -1.25, 2])
        #expect(json["gravity"] as? [Double] == [0, -0.25, -0.968])
        #expect(json["accel"] as? [Double] == [0.01, 0, -0.02])
        #expect(json["quat"] as? [Double] == [0.9, 0.1, -0.3, 0.3])
    }

    @Test("sample datagram is one line the controller can split on")
    func singleLine() {
        let text = String(decoding: encodeLine(.sample(sample)), as: UTF8.self)
        #expect(!text.contains("\n"))
    }

    @Test("status uses its lowercase wire name", arguments: HeadphoneStatus.allCases)
    func statusNames(status: HeadphoneStatus) throws {
        let json = try decode(encodeLine(.status(status)))
        #expect(json["type"] as? String == "status")
        #expect(json["status"] as? String == status.rawValue)
    }

    @Test("status names match what macos_motion.py accepts")
    func statusContract() {
        #expect(HeadphoneStatus.allCases.map(\.rawValue) == ["connected", "disconnected", "unavailable", "denied"])
    }
}

@Suite("Helper options")
struct HelperOptionsTests {
    @Test("port and parent pid are read in any order",
          arguments: [["--port", "48737", "--parent-pid", "4242"], ["--parent-pid", "4242", "--port", "48737"]])
    func parsesBoth(arguments: [String]) {
        #expect(HelperOptions.parse(arguments) == HelperOptions(port: 48737, parentPID: 4242))
    }

    @Test("incomplete or invalid options are rejected", arguments: [
        [],
        ["--port", "48737"],
        ["--parent-pid", "4242"],
        ["--port", "0", "--parent-pid", "4242"],
        ["--port", "70000", "--parent-pid", "4242"],
        ["--port", "abc", "--parent-pid", "4242"],
        ["--port", "48737", "--parent-pid", "1"],
        ["--port", "48737", "--parent-pid"],
        ["48737", "--parent-pid", "4242"],
    ] as [[String]])
    func rejects(arguments: [String]) {
        #expect(HelperOptions.parse(arguments) == nil)
    }
}
