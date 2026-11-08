// swift-tools-version: 6.0
// SPDX-License-Identifier: Apache-2.0
import PackageDescription

let package = Package(
    name: "mousepods-macos",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "mousepods-motion", targets: ["mousepods-motion"]),
    ],
    targets: [
        .target(name: "MotionWire"),
        .executableTarget(
            name: "mousepods-motion",
            dependencies: ["MotionWire"],
            linkerSettings: [.linkedFramework("CoreMotion"), .linkedFramework("Carbon"), .linkedFramework("AppKit"), .linkedFramework("MediaPlayer"), .linkedFramework("AVFoundation"), .linkedFramework("Vision")]
        ),
        .testTarget(name: "MotionWireTests", dependencies: ["MotionWire"]),
    ]
)
