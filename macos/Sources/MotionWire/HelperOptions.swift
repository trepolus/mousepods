// SPDX-License-Identifier: Apache-2.0

/// Command-line options, passed by the Python controller through `open --args`.
public struct HelperOptions: Equatable, Sendable {
    /// UDP port on 127.0.0.1 that the controller listens on.
    public let port: UInt16
    /// The helper exits once this process is gone, so it never outlives the controller.
    public let parentPID: Int32

    public init(port: UInt16, parentPID: Int32) {
        self.port = port
        self.parentPID = parentPID
    }

    /// Parses `--port N --parent-pid P`; returns nil when either is missing or out of range.
    public static func parse(_ arguments: [String]) -> HelperOptions? {
        var values: [String: String] = [:]
        var index = arguments.startIndex
        while index < arguments.endIndex {
            let key = arguments[index]
            let next = arguments.index(after: index)
            guard key.hasPrefix("--"), next < arguments.endIndex else { return nil }
            values[key] = arguments[next]
            index = arguments.index(after: next)
        }
        guard let port = values["--port"].flatMap(UInt16.init), port > 0,
              let parent = values["--parent-pid"].flatMap(Int32.init), parent > 1
        else { return nil }
        return HelperOptions(port: port, parentPID: parent)
    }
}
