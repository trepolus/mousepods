// SPDX-License-Identifier: Apache-2.0
// Hand gestures from camera hand landmarks (Apple Vision): pinches of the thumb with one finger, and a fist.
// Pure: landmarks and times in, events out. Distances are relative to the hand size, so the distance to the
// camera does not matter.

public struct Point2: Equatable, Sendable {
    public let x: Double
    public let y: Double

    public init(x: Double, y: Double) {
        self.x = x
        self.y = y
    }

    func distance(to other: Point2) -> Double {
        ((x - other.x) * (x - other.x) + (y - other.y) * (y - other.y)).squareRoot()
    }
}

/// The landmarks the classifier uses, in any consistent 2D unit (Vision gives normalised image coordinates).
public struct HandLandmarks: Equatable, Sendable {
    public let wrist: Point2
    public let middleBase: Point2      // middle finger MCP joint: wrist to here is the hand size
    public let thumbTip: Point2
    public let indexTip: Point2
    public let middleTip: Point2
    public let ringTip: Point2
    public let littleTip: Point2

    public init(wrist: Point2, middleBase: Point2, thumbTip: Point2, indexTip: Point2, middleTip: Point2,
                ringTip: Point2, littleTip: Point2) {
        self.wrist = wrist
        self.middleBase = middleBase
        self.thumbTip = thumbTip
        self.indexTip = indexTip
        self.middleTip = middleTip
        self.ringTip = ringTip
        self.littleTip = littleTip
    }

    var size: Double { wrist.distance(to: middleBase) }

    func tip(_ finger: PinchFinger) -> Point2 {
        switch finger {
        case .index: indexTip
        case .middle: middleTip
        case .ring: ringTip
        }
    }
}

public enum PinchFinger: String, Sendable, CaseIterable {
    case index
    case middle
    case ring
}

public enum HandEvent: Equatable, Sendable {
    case pinchDown(PinchFinger)
    case pinchUp(PinchFinger)
    case fist
}

public struct HandGestureClassifier: Sendable {
    /// Thumb to fingertip, relative to hand size: closer than `pinchOn` starts a pinch, farther than
    /// `pinchOff` ends it (the gap keeps a borderline pinch from flickering).
    public var pinchOn = 0.25
    public var pinchOff = 0.35
    /// All four fingertips within `fistReach` hand sizes of the wrist for `fistHold` seconds = fist.
    public var fistReach = 1.1
    public var fistHold = 0.5

    private var pinched: PinchFinger?
    private var fistSince: Double?
    private var fistFired = false

    public init() {}

    /// One camera frame. `hand` is nil when no hand is visible; an open pinch is then released.
    public mutating func update(_ hand: HandLandmarks?, at time: Double) -> [HandEvent] {
        guard let hand, hand.size > 0 else {
            fistSince = nil
            fistFired = false
            return releasePinch()
        }
        let size = hand.size
        var events: [HandEvent] = []

        let tips = [hand.indexTip, hand.middleTip, hand.ringTip, hand.littleTip]
        let isFist = tips.allSatisfy { $0.distance(to: hand.wrist) / size < fistReach }
        if isFist {
            events += releasePinch()          // a closing fist brings the thumb near the fingers: not a pinch
            if fistSince == nil { fistSince = time }
            if !fistFired, let since = fistSince, time - since >= fistHold {
                fistFired = true
                events.append(.fist)
            }
            return events
        }
        fistSince = nil
        fistFired = false

        if let finger = pinched {
            if hand.thumbTip.distance(to: hand.tip(finger)) / size > pinchOff {
                events += releasePinch()
            }
            return events
        }
        let closest = PinchFinger.allCases
            .map { ($0, hand.thumbTip.distance(to: hand.tip($0)) / size) }
            .min { $0.1 < $1.1 }
        if let (finger, ratio) = closest, ratio < pinchOn {
            pinched = finger
            events.append(.pinchDown(finger))
        }
        return events
    }

    private mutating func releasePinch() -> [HandEvent] {
        guard let finger = pinched else { return [] }
        pinched = nil
        return [.pinchUp(finger)]
    }
}
