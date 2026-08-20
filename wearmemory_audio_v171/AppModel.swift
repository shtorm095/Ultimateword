import Foundation
import UIKit
import Combine

final class AppModel: ObservableObject {
    @Published private(set) var batteryLevel: Float = -1

    let audio = AudioBufferManager()
    var driveSync = GoogleDriveSync()

    private let integrationBridge = AudioIntegrationBridge()
    private var lastCompletedAudioFile: String?
    private var lastCompletedAt: Date?
    private var batteryObserver: NSObjectProtocol?
    private var cancellables = Set<AnyCancellable>()

    init() {
        // WearMemory Audio has exactly one primary job: record audio.
        // Speech/Text processing is deliberately disabled and belongs to WearMemory Text.
        audio.transcribeSegments = false
        audio.onSegmentReady = nil

        audio.objectWillChange
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in self?.objectWillChange.send() }
            .store(in: &cancellables)

        audio.onSegmentCompleted = { [weak self] url, start, end in
            guard let self = self else { return }

            // Drive stays the primary independent destination.
            // The passive bridge is not in the Drive path and cannot block Drive scheduling.
            self.driveSync.enqueueAudio(url)

            self.lastCompletedAudioFile = url.lastPathComponent
            self.lastCompletedAt = end

            self.integrationBridge.exportFinalizedAudio(url, startedAt: start, endedAt: end)
            self.publishIntegrationStatus()
        }

        audio.$isRecording
            .sink { [weak self] _ in DispatchQueue.main.async { self?.publishIntegrationStatus() } }
            .store(in: &cancellables)
        audio.$statusText
            .sink { [weak self] _ in DispatchQueue.main.async { self?.publishIntegrationStatus() } }
            .store(in: &cancellables)
        driveSync.$statusText
            .sink { [weak self] _ in DispatchQueue.main.async { self?.publishIntegrationStatus() } }
            .store(in: &cancellables)
        driveSync.$pendingCount
            .sink { [weak self] _ in DispatchQueue.main.async { self?.publishIntegrationStatus() } }
            .store(in: &cancellables)
        driveSync.$lastError
            .sink { [weak self] _ in DispatchQueue.main.async { self?.publishIntegrationStatus() } }
            .store(in: &cancellables)

        UIDevice.current.isBatteryMonitoringEnabled = true
        batteryLevel = UIDevice.current.batteryLevel
        batteryObserver = NotificationCenter.default.addObserver(
            forName: UIDevice.batteryLevelDidChangeNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            self?.batteryLevel = UIDevice.current.batteryLevel
        }

        publishIntegrationStatus()
    }

    deinit {
        if let o = batteryObserver { NotificationCenter.default.removeObserver(o) }
    }

    func requestPermissions() {
        audio.requestMicPermission { _ in }
    }

    private func publishIntegrationStatus() {
        let info = Bundle.main.infoDictionary ?? [:]
        integrationBridge.publishStatus(.init(
            bridgeVersion: AudioIntegrationBridge.bridgeVersion,
            module: "audio",
            appVersion: info["CFBundleShortVersionString"] as? String ?? "",
            build: info["CFBundleVersion"] as? String ?? "",
            isRecording: audio.isRecording,
            audioStatus: audio.statusText,
            driveStatus: driveSync.statusText,
            drivePendingCount: driveSync.pendingCount,
            driveLastError: driveSync.lastError,
            lastCompletedAudioFile: lastCompletedAudioFile,
            lastCompletedAt: lastCompletedAt,
            updatedAt: Date()
        ))
    }
}
