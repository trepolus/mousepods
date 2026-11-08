// SPDX-License-Identifier: Apache-2.0
// Camera hand tracking: AVFoundation frames -> Vision hand pose -> HandGestureClassifier -> hand events.
// Thin adapter: every decision lives in MotionWire.HandGestureClassifier.
import AVFoundation
import Foundation
import MotionWire
import Vision

final class HandTracker: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate, @unchecked Sendable {
    private let sender: UDPSender
    private let queue = DispatchQueue(label: "mousepods.hands")
    private let request: VNDetectHumanHandPoseRequest = {
        let r = VNDetectHumanHandPoseRequest()
        r.maximumHandCount = 1
        return r
    }()
    private var session: AVCaptureSession?
    private var classifier = HandGestureClassifier()      // only touched on `queue`

    init(sender: UDPSender) {
        self.sender = sender
    }

    func set(_ on: Bool) {
        queue.async { on ? self.start() : self.stop() }
    }

    private func start() {
        guard session == nil else { return }
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            break
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { granted in
                if granted { self.set(true) } else { NSLog("mousepods-motion: camera access denied") }
            }
            return
        default:
            NSLog("mousepods-motion: camera access denied")
            return
        }
        guard let device = AVCaptureDevice.default(for: .video),
              let input = try? AVCaptureDeviceInput(device: device)
        else {
            NSLog("mousepods-motion: no camera")
            return
        }
        let session = AVCaptureSession()
        session.sessionPreset = .medium
        let output = AVCaptureVideoDataOutput()
        output.alwaysDiscardsLateVideoFrames = true
        output.setSampleBufferDelegate(self, queue: queue)
        guard session.canAddInput(input), session.canAddOutput(output) else { return }
        session.addInput(input)
        session.addOutput(output)
        session.startRunning()
        self.session = session
        NSLog("mousepods-motion: camera on")
    }

    private func stop() {
        guard let session else { return }
        session.stopRunning()
        self.session = nil
        for event in classifier.update(nil, at: ProcessInfo.processInfo.systemUptime) {   // release a held pinch
            sender.send(.hand(event))
        }
        NSLog("mousepods-motion: camera off")
    }

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer,
                       from connection: AVCaptureConnection) {
        let time = CMSampleBufferGetPresentationTimeStamp(sampleBuffer).seconds
        let handler = VNImageRequestHandler(cmSampleBuffer: sampleBuffer, orientation: .up)
        // Vision normalises x and y separately; scale x by the aspect ratio so distances are true to shape.
        var aspect = 1.0
        if let pixels = CMSampleBufferGetImageBuffer(sampleBuffer), CVPixelBufferGetHeight(pixels) > 0 {
            aspect = Double(CVPixelBufferGetWidth(pixels)) / Double(CVPixelBufferGetHeight(pixels))
        }
        let landmarks = (try? handler.perform([request])).flatMap { _ in request.results?.first }
            .flatMap { Self.landmarks($0, aspect: aspect) }
        for event in classifier.update(landmarks, at: time) {
            sender.send(.hand(event))
        }
    }

    private static func landmarks(_ hand: VNHumanHandPoseObservation, aspect: Double) -> HandLandmarks? {
        func point(_ joint: VNHumanHandPoseObservation.JointName) -> Point2? {
            guard let p = try? hand.recognizedPoint(joint), p.confidence > 0.3 else { return nil }
            return Point2(x: Double(p.location.x) * aspect, y: Double(p.location.y))
        }
        guard let wrist = point(.wrist), let middleBase = point(.middleMCP), let thumb = point(.thumbTip),
              let index = point(.indexTip), let middle = point(.middleTip), let ring = point(.ringTip),
              let little = point(.littleTip)
        else { return nil }
        return HandLandmarks(wrist: wrist, middleBase: middleBase, thumbTip: thumb, indexTip: index,
                             middleTip: middle, ringTip: ring, littleTip: little)
    }
}
