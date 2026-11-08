// SPDX-License-Identifier: Apache-2.0
// Wire format between the macOS motion helper and the Python controller: one JSON object per UDP datagram.
// Values keep CoreMotion's units (rad/s, g, unit quaternion); macos_motion.py converts them to engine units.
import Foundation

public struct Vector3: Equatable, Sendable {
    public let x: Double
    public let y: Double
    public let z: Double

    public init(x: Double, y: Double, z: Double) {
        self.x = x
        self.y = y
        self.z = z
    }
}

public struct Quaternion: Equatable, Sendable {
    public let w: Double
    public let x: Double
    public let y: Double
    public let z: Double

    public init(w: Double, x: Double, y: Double, z: Double) {
        self.w = w
        self.x = x
        self.y = y
        self.z = z
    }
}

/// One CMDeviceMotion reading from the headphones.
public struct MotionSample: Equatable, Sendable {
    /// Seconds since boot (CMLogItem.timestamp).
    public let timestamp: Double
    /// Radians per second, device frame.
    public let rotationRate: Vector3
    /// In g, device frame.
    public let gravity: Vector3
    /// In g, gravity removed, device frame.
    public let userAcceleration: Vector3
    public let attitude: Quaternion

    public init(timestamp: Double, rotationRate: Vector3, gravity: Vector3, userAcceleration: Vector3,
                attitude: Quaternion) {
        self.timestamp = timestamp
        self.rotationRate = rotationRate
        self.gravity = gravity
        self.userAcceleration = userAcceleration
        self.attitude = attitude
    }
}

public enum HeadphoneStatus: String, Sendable, CaseIterable {
    /// Supported headphones are connected; samples follow while they are worn.
    case connected
    /// Headphones went away (taken out, case closed, switched to another device).
    case disconnected
    /// macOS reports no headphone motion support (no supported headphones ever seen).
    case unavailable
    /// Motion & Fitness permission denied or restricted for the helper app.
    case denied
}

public enum HelperEvent: Equatable, Sendable {
    case sample(MotionSample)
    case status(HeadphoneStatus)
}

/// Frozen wire DTOs: field names are the contract with macos_motion.py.
private struct SampleDTO: Encodable {
    let type = "sample"
    let t: Double
    let rate: [Double]
    let gravity: [Double]
    let accel: [Double]
    let quat: [Double]
}

private struct StatusDTO: Encodable {
    let type = "status"
    let status: String
}

private extension Vector3 {
    var wire: [Double] { [x, y, z] }
}

public func encodeLine(_ event: HelperEvent) -> Data {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.sortedKeys]
    switch event {
    case .sample(let s):
        let a = s.attitude
        let dto = SampleDTO(t: s.timestamp, rate: s.rotationRate.wire, gravity: s.gravity.wire,
                            accel: s.userAcceleration.wire, quat: [a.w, a.x, a.y, a.z])
        // Encoding plain numbers and strings cannot fail.
        return try! encoder.encode(dto)
    case .status(let status):
        return try! encoder.encode(StatusDTO(status: status.rawValue))
    }
}
