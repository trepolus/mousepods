// SPDX-License-Identifier: Apache-2.0

/// macOS can report one stem press as two remote commands (play/pause and pause) a few milliseconds apart.
/// Collapses presses of the same kind that arrive within `window` seconds into one.
public struct StemDebouncer: Sendable {
    public let window: Double
    private var last: (press: StemPress, at: Double)?

    public init(window: Double = 0.25) {
        self.window = window
    }

    /// Returns the press to forward, or nil when it repeats the previous one inside the window.
    public mutating func accept(_ press: StemPress, at time: Double) -> StemPress? {
        if let last, last.press == press, time - last.at < window {
            return nil
        }
        last = (press, time)
        return press
    }
}
