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

@Suite("Hotkeys")
struct HotkeyTests {
    @Test("command uses the name the controller accepts from --send", arguments: HotkeyCommand.allCases)
    func commandWire(command: HotkeyCommand) throws {
        let json = try decode(encodeLine(.command(command)))
        #expect(json["type"] as? String == "command")
        #expect(json["command"] as? String == command.rawValue)
    }

    @Test("command names match the controller's --send commands")
    func commandContract() {
        #expect(HotkeyCommand.allCases.map(\.rawValue) == ["recenter", "toggle", "scroll", "mode"])
    }

    @Test("every command has exactly one shortcut and no two shortcuts collide")
    func uniqueBindings() {
        #expect(defaultHotkeys.map(\.command).sorted { $0.rawValue < $1.rawValue }
                == HotkeyCommand.allCases.sorted { $0.rawValue < $1.rawValue })
        let keys = defaultHotkeys.map { "\($0.keyCode)-\($0.modifiers)" }
        #expect(Set(keys).count == keys.count)
    }

    @Test("shortcuts use Control+Option like Control+Alt on Linux")
    func modifiers() {
        #expect(defaultHotkeys.allSatisfy { $0.modifiers == CarbonModifier.control | CarbonModifier.option })
    }
}

@Suite("Stem presses and controller messages")
struct StemTests {
    @Test("stem press uses its wire name", arguments: StemPress.allCases)
    func stemWire(press: StemPress) throws {
        let json = try decode(encodeLine(.stem(press)))
        #expect(json["type"] as? String == "stem")
        #expect(json["press"] as? String == press.rawValue)
    }

    @Test("controller can claim and release Now Playing", arguments: [
        ("{\"type\":\"control\",\"now_playing\":true}", HelperControl?.some(.nowPlaying(true))),
        ("{\"type\":\"control\",\"now_playing\":false}", HelperControl?.some(.nowPlaying(false))),
    ] as [(String, HelperControl?)])
    func controlParses(text: String, want: HelperControl?) {
        #expect(HelperControl.parse(Data(text.utf8)) == want)
    }

    @Test("anything else from the controller is ignored", arguments: [
        "{\"type\":\"control\",\"now_playing\":1}",
        "{\"type\":\"control\"}",
        "{\"type\":\"status\",\"now_playing\":true}",
        "[true]",
        "nope",
    ] as [String])
    func controlRejects(text: String) {
        #expect(HelperControl.parse(Data(text.utf8)) == nil)
    }
}

@Suite("Stem debouncing")
struct StemDebouncerTests {
    @Test("one press reported twice by macOS is forwarded once")
    func duplicate() {
        var d = StemDebouncer()
        #expect(d.accept(.single, at: 10.000) == .single)
        #expect(d.accept(.single, at: 10.004) == nil)
    }

    @Test("two separate presses are both forwarded")
    func separate() {
        var d = StemDebouncer()
        #expect(d.accept(.single, at: 10.0) == .single)
        #expect(d.accept(.single, at: 10.6) == .single)
    }

    @Test("a different press right after is not swallowed")
    func differentKind() {
        var d = StemDebouncer()
        #expect(d.accept(.single, at: 10.0) == .single)
        #expect(d.accept(.double, at: 10.05) == .double)
    }

    @Test("the window counts from the last forwarded press")
    func window() {
        var d = StemDebouncer(window: 0.25)
        #expect(d.accept(.single, at: 0.0) == .single)
        #expect(d.accept(.single, at: 0.2) == nil)
        #expect(d.accept(.single, at: 0.3) == .single)
    }
}
