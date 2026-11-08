// SPDX-License-Identifier: Apache-2.0

/// A system-wide shortcut: Carbon virtual key code plus Carbon modifier mask.
public struct Hotkey: Equatable, Sendable {
    public let keyCode: UInt32
    public let modifiers: UInt32
    public let command: HotkeyCommand

    public init(keyCode: UInt32, modifiers: UInt32, command: HotkeyCommand) {
        self.keyCode = keyCode
        self.modifiers = modifiers
        self.command = command
    }
}

/// Carbon modifier bits (HIToolbox Events.h).
public enum CarbonModifier {
    public static let control: UInt32 = 1 << 12
    public static let option: UInt32 = 1 << 11
}

/// Same letters as the GNOME shortcuts on Linux (HOTKEYS in airpods_mouse_controller.py), with
/// Control+Option standing in for Control+Alt. Key codes are kVK_ANSI_* from HIToolbox Events.h.
public let defaultHotkeys: [Hotkey] = [
    Hotkey(keyCode: 8, modifiers: CarbonModifier.control | CarbonModifier.option, command: .recenter),   // C
    Hotkey(keyCode: 35, modifiers: CarbonModifier.control | CarbonModifier.option, command: .toggle),    // P
    Hotkey(keyCode: 1, modifiers: CarbonModifier.control | CarbonModifier.option, command: .scroll),     // S
    Hotkey(keyCode: 46, modifiers: CarbonModifier.control | CarbonModifier.option, command: .mode),      // M
]
