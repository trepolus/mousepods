// SPDX-License-Identifier: Apache-2.0
// mousepods-motion: reads AirPods head tracking through CoreMotion and sends it to the MousePods
// controller as UDP datagrams on 127.0.0.1 (format: MotionWire). Started by the controller with
// `open MousePodsMotion.app --args --port N --parent-pid P`; exits when the controller is gone.
import AppKit
import Carbon.HIToolbox
import CoreMotion
import Darwin
import Foundation
import MotionWire

final class UDPSender: @unchecked Sendable {
    private let fd: Int32
    private var address: sockaddr_in

    init?(port: UInt16) {
        fd = socket(AF_INET, SOCK_DGRAM, 0)
        guard fd >= 0 else { return nil }
        address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = port.bigEndian
        address.sin_addr.s_addr = inet_addr("127.0.0.1")
    }

    /// Fire and forget: a datagram nobody listens for is simply dropped.
    func send(_ event: HelperEvent) {
        let data = encodeLine(event)
        data.withUnsafeBytes { bytes in
            withUnsafePointer(to: &address) { pointer in
                pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { addr in
                    _ = sendto(fd, bytes.baseAddress, bytes.count, 0, addr, socklen_t(MemoryLayout<sockaddr_in>.size))
                }
            }
        }
    }
}

final class HeadphoneDelegate: NSObject, CMHeadphoneMotionManagerDelegate {
    let sender: UDPSender

    init(sender: UDPSender) {
        self.sender = sender
    }

    func headphoneMotionManagerDidConnect(_ manager: CMHeadphoneMotionManager) {
        sender.send(.status(.connected))
    }

    func headphoneMotionManagerDidDisconnect(_ manager: CMHeadphoneMotionManager) {
        sender.send(.status(.disconnected))
    }
}

extension MotionSample {
    init(_ m: CMDeviceMotion) {
        let r = m.rotationRate, g = m.gravity, a = m.userAcceleration, q = m.attitude.quaternion
        self.init(
            timestamp: m.timestamp,
            rotationRate: Vector3(x: r.x, y: r.y, z: r.z),
            gravity: Vector3(x: g.x, y: g.y, z: g.z),
            userAcceleration: Vector3(x: a.x, y: a.y, z: a.z),
            attitude: Quaternion(w: q.w, x: q.x, y: q.y, z: q.z)
        )
    }
}

func isDeniedError(_ error: Error) -> Bool {
    let ns = error as NSError
    return ns.domain == CMErrorDomain && ns.code == Int(CMErrorMotionActivityNotAuthorized.rawValue)
}

/// CoreMotion calls this on its background queue. It must be built outside top-level code: closures
/// written there are main-actor isolated in Swift 6, and the runtime traps when they run off the main thread.
func makeMotionHandler(sender: UDPSender) -> CMHeadphoneMotionManager.DeviceMotionHandler {
    { @Sendable motion, error in
        if let error {
            sender.send(.status(isDeniedError(error) ? .denied : .disconnected))
            return
        }
        if let motion {
            sender.send(.sample(MotionSample(motion)))
        }
    }
}

/// Owns the registered shortcuts; Carbon calls back with the index as the hot key id.
final class HotkeyRegistry: @unchecked Sendable {
    let sender: UDPSender
    let hotkeys: [Hotkey]
    private var refs: [EventHotKeyRef?] = []

    init(sender: UDPSender, hotkeys: [Hotkey]) {
        self.sender = sender
        self.hotkeys = hotkeys
    }

    func fire(_ index: Int) {
        guard hotkeys.indices.contains(index) else { return }
        sender.send(.command(hotkeys[index].command))
    }

    /// Registers every shortcut; returns the ones another app already holds.
    func register() -> [Hotkey] {
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        let handler: EventHandlerUPP = { _, event, userData in
            var id = EventHotKeyID()
            GetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID),
                              nil, MemoryLayout<EventHotKeyID>.size, nil, &id)
            if let userData {
                Unmanaged<HotkeyRegistry>.fromOpaque(userData).takeUnretainedValue().fire(Int(id.id))
            }
            return noErr
        }
        InstallEventHandler(GetApplicationEventTarget(), handler, 1, &spec,
                            Unmanaged.passUnretained(self).toOpaque(), nil)
        var taken: [Hotkey] = []
        for (index, hotkey) in hotkeys.enumerated() {
            var ref: EventHotKeyRef?
            let id = EventHotKeyID(signature: OSType(0x4D50_4D53), id: UInt32(index))   // "MPMS"
            let status = RegisterEventHotKey(hotkey.keyCode, hotkey.modifiers, id, GetApplicationEventTarget(), 0, &ref)
            if status == noErr {
                refs.append(ref)
            } else {
                taken.append(hotkey)
            }
        }
        return taken
    }
}

func processIsGone(_ pid: Int32) -> Bool {
    kill(pid, 0) != 0 && errno == ESRCH
}

// `open --args` may prepend nothing, but Finder launches add -psn_...; keep only our flags.
let arguments = Array(CommandLine.arguments.dropFirst()).filter { !$0.hasPrefix("-psn_") }
guard let options = HelperOptions.parse(arguments) else {
    FileHandle.standardError.write(Data("usage: mousepods-motion --port N --parent-pid P\n".utf8))
    exit(2)
}
guard let sender = UDPSender(port: options.port) else {
    FileHandle.standardError.write(Data("mousepods-motion: cannot open a UDP socket\n".utf8))
    exit(1)
}

let manager = CMHeadphoneMotionManager()
let delegate = HeadphoneDelegate(sender: sender)
manager.delegate = delegate

switch CMHeadphoneMotionManager.authorizationStatus() {
case .denied, .restricted:
    sender.send(.status(.denied))
case .notDetermined, .authorized:
    break
@unknown default:
    break
}

if !manager.isDeviceMotionAvailable {
    sender.send(.status(.unavailable))
}

let queue = OperationQueue()
queue.maxConcurrentOperationCount = 1
manager.startDeviceMotionUpdates(to: queue, withHandler: makeMotionHandler(sender: sender))

let watchdog = Timer(timeInterval: 1.0, repeats: true) { _ in
    // Scheduled on the main run loop below, so this always runs on the main thread.
    MainActor.assumeIsolated {
        if processIsGone(options.parentPID) {
            manager.stopDeviceMotionUpdates()
            exit(0)
        }
    }
}
RunLoop.main.add(watchdog, forMode: .common)

let hotkeys = HotkeyRegistry(sender: sender, hotkeys: defaultHotkeys)
for hotkey in hotkeys.register() {
    FileHandle.standardError.write(Data("mousepods-motion: shortcut for \(hotkey.command.rawValue) is taken\n".utf8))
}

// An accessory NSApplication (no Dock icon, no menu bar) so Carbon delivers hot key events.
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
app.run()
