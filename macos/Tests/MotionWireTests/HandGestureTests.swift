// SPDX-License-Identifier: Apache-2.0
import MotionWire
import Testing

/// Hand of size 1 (wrist to middle base), fingers spread unless moved.
private func hand(thumb: Point2 = Point2(x: -0.6, y: 0.8), index: Point2 = Point2(x: -0.3, y: 1.8),
                  middle: Point2 = Point2(x: 0, y: 1.9), ring: Point2 = Point2(x: 0.3, y: 1.8),
                  little: Point2 = Point2(x: 0.55, y: 1.5)) -> HandLandmarks {
    HandLandmarks(wrist: Point2(x: 0, y: 0), middleBase: Point2(x: 0, y: 1), thumbTip: thumb, indexTip: index,
                  middleTip: middle, ringTip: ring, littleTip: little)
}

private func touching(_ tip: Point2) -> Point2 { Point2(x: tip.x + 0.05, y: tip.y) }

private let indexTip = Point2(x: -0.3, y: 1.8)
private let middleTip = Point2(x: 0, y: 1.9)
private let ringTip = Point2(x: 0.3, y: 1.8)

@Suite("Hand gestures")
struct HandGestureTests {
    @Test("open hand does nothing")
    func openHand() {
        var c = HandGestureClassifier()
        #expect(c.update(hand(), at: 0) == [])
    }

    @Test("thumb on a fingertip pinches that finger",
          arguments: [(indexTip, PinchFinger.index), (middleTip, .middle), (ringTip, .ring)] as [(Point2, PinchFinger)])
    func pinchFinger(tip: Point2, finger: PinchFinger) {
        var c = HandGestureClassifier()
        #expect(c.update(hand(thumb: touching(tip)), at: 0) == [.pinchDown(finger)])
        #expect(c.update(hand(), at: 0.2) == [.pinchUp(finger)])
    }

    @Test("pinch held over many frames is one down and one up")
    func holdIsOneEvent() {
        var c = HandGestureClassifier()
        var events: [HandEvent] = []
        for frame in 0..<20 {
            events += c.update(hand(thumb: touching(indexTip)), at: Double(frame) / 30)
        }
        events += c.update(hand(), at: 1)
        #expect(events == [.pinchDown(.index), .pinchUp(.index)])
    }

    @Test("borderline distance between on and off does not flicker")
    func hysteresis() {
        var c = HandGestureClassifier()
        _ = c.update(hand(thumb: touching(indexTip)), at: 0)
        // 0.30 hand sizes away: above pinchOn (0.25) but below pinchOff (0.35): stays pinched.
        #expect(c.update(hand(thumb: Point2(x: indexTip.x + 0.30, y: indexTip.y)), at: 0.1) == [])
        #expect(c.update(hand(thumb: Point2(x: indexTip.x + 0.40, y: indexTip.y)), at: 0.2) == [.pinchUp(.index)])
    }

    @Test("hand leaving the camera releases a held pinch")
    func handLost() {
        var c = HandGestureClassifier()
        _ = c.update(hand(thumb: touching(indexTip)), at: 0)
        #expect(c.update(nil, at: 0.5) == [.pinchUp(.index)])
        #expect(c.update(nil, at: 0.6) == [])
    }

    @Test("fist held for half a second fires once")
    func fist() {
        let closed = hand(thumb: Point2(x: 0.2, y: 0.7), index: Point2(x: -0.2, y: 0.8), middle: Point2(x: 0, y: 0.8),
                          ring: Point2(x: 0.2, y: 0.8), little: Point2(x: 0.35, y: 0.7))
        var c = HandGestureClassifier()
        var events: [HandEvent] = []
        for frame in 0...30 {
            events += c.update(closed, at: Double(frame) / 30)
        }
        #expect(events == [.fist])
    }

    @Test("closing into a fist is not taken as a pinch")
    func fistIsNotPinch() {
        let closed = hand(thumb: Point2(x: -0.15, y: 0.8), index: Point2(x: -0.2, y: 0.8), middle: Point2(x: 0, y: 0.8),
                          ring: Point2(x: 0.2, y: 0.8), little: Point2(x: 0.35, y: 0.7))
        var c = HandGestureClassifier()
        #expect(c.update(closed, at: 0) == [])
    }

    @Test("short fist does not pause")
    func shortFist() {
        let closed = hand(thumb: Point2(x: 0.2, y: 0.7), index: Point2(x: -0.2, y: 0.8), middle: Point2(x: 0, y: 0.8),
                          ring: Point2(x: 0.2, y: 0.8), little: Point2(x: 0.35, y: 0.7))
        var c = HandGestureClassifier()
        _ = c.update(closed, at: 0)
        _ = c.update(closed, at: 0.3)
        #expect(c.update(hand(), at: 0.4) == [])
    }
}
