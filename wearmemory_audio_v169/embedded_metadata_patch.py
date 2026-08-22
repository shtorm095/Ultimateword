from pathlib import Path
import subprocess

root = Path('/tmp/wm169')
model = root/'WearMemory/AppModel.swift'
info = root/'WearMemory/Info.plist'

s = model.read_text()
if 'import AVFoundation\n' not in s:
    if 'import Foundation\n' in s:
        s = s.replace('import Foundation\n', 'import Foundation\nimport AVFoundation\n', 1)
    else:
        s = 'import AVFoundation\n' + s

start = s.index('    private func handoffAudioToText(_ sourceURL: URL, startedAt: Date, endedAt: Date) {')
end = s.index('\n    deinit {', start)
new_handoff = r'''    private static let wearMemoryMetadataPrefix = "WEARMEMORY_META_V1:"

    private func handoffAudioToText(_ sourceURL: URL, startedAt: Date, endedAt: Date) {
        let fm = FileManager.default
        guard let root = fm.containerURL(forSecurityApplicationGroupIdentifier: Self.sharedGroupIdentifier) else {
            return
        }

        do {
            let inbox = root.appendingPathComponent("AudioInbox", isDirectory: true)
            let staging = root.appendingPathComponent("AudioInboxStaging", isDirectory: true)
            try fm.createDirectory(at: inbox, withIntermediateDirectories: true)
            try fm.createDirectory(at: staging, withIntermediateDirectories: true)

            // The staging file is outside AudioInbox, so WearMemory Text cannot see it
            // until the copy AND embedded metadata write are completely finished.
            let stageURL = staging.appendingPathComponent(UUID().uuidString + ".m4a")
            try? fm.removeItem(at: stageURL)
            try fm.copyItem(at: sourceURL, to: stageURL)

            let iso = ISO8601DateFormatter()
            let metadata: [String: Any] = [
                "wearMemoryMetadataVersion": 1,
                "bridgeVersion": 3,
                "recordingId": sourceURL.deletingPathExtension().lastPathComponent,
                "sourceFileName": sourceURL.lastPathComponent,
                "startedAt": iso.string(from: startedAt),
                "endedAt": iso.string(from: endedAt),
                "exportedAt": iso.string(from: Date()),
                "speechStatus": "pending_ipod",
                "ipadStatus": "queued",
                "ipadUpdatedAt": iso.string(from: Date())
            ]
            try Self.writeWearMemoryMetadata(metadata, to: stageURL)

            let finalURL = inbox.appendingPathComponent(sourceURL.lastPathComponent)
            if fm.fileExists(atPath: finalURL.path) { try fm.removeItem(at: finalURL) }
            try fm.moveItem(at: stageURL, to: finalURL)

            // Remove any legacy sidecar with the same basename left by an older Audio build.
            let legacySidecar = inbox.appendingPathComponent(sourceURL.deletingPathExtension().lastPathComponent + ".meta.json")
            try? fm.removeItem(at: legacySidecar)
        } catch {
            // The original AudioBuffer recording is never modified or deleted.
        }
    }

    private static func writeWearMemoryMetadata(_ object: [String: Any], to sourceURL: URL) throws {
        let fm = FileManager.default
        let jsonData = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        guard let json = String(data: jsonData, encoding: .utf8) else {
            throw NSError(domain: "WearMemoryAudio.Metadata", code: 1, userInfo: [NSLocalizedDescriptionKey: "Не удалось кодировать metadata"])
        }

        let asset = AVURLAsset(url: sourceURL)
        let compatible = AVAssetExportSession.exportPresets(compatibleWith: asset)
        let preset = compatible.contains(AVAssetExportPresetPassthrough) ? AVAssetExportPresetPassthrough : AVAssetExportPresetAppleM4A
        guard let exporter = AVAssetExportSession(asset: asset, presetName: preset) else {
            throw NSError(domain: "WearMemoryAudio.Metadata", code: 2, userInfo: [NSLocalizedDescriptionKey: "Не удалось открыть M4A для metadata"])
        }

        let tempURL = sourceURL.deletingLastPathComponent().appendingPathComponent(".wmmeta-\(UUID().uuidString).m4a")
        try? fm.removeItem(at: tempURL)
        exporter.outputURL = tempURL
        exporter.outputFileType = .m4a

        let metadataItem = AVMutableMetadataItem()
        metadataItem.identifier = .quickTimeMetadataDescription
        metadataItem.value = (wearMemoryMetadataPrefix + json) as NSString
        let preserved = asset.metadata.filter { item in
            guard item.identifier == .quickTimeMetadataDescription,
                  let value = item.stringValue else { return true }
            return !value.hasPrefix(wearMemoryMetadataPrefix)
        }
        exporter.metadata = preserved + [metadataItem]

        let semaphore = DispatchSemaphore(value: 0)
        exporter.exportAsynchronously { semaphore.signal() }
        guard semaphore.wait(timeout: .now() + 60) == .success else {
            exporter.cancelExport()
            try? fm.removeItem(at: tempURL)
            throw NSError(domain: "WearMemoryAudio.Metadata", code: 3, userInfo: [NSLocalizedDescriptionKey: "Timeout записи metadata в M4A"])
        }
        guard exporter.status == .completed, fm.fileExists(atPath: tempURL.path) else {
            let error = exporter.error ?? NSError(domain: "WearMemoryAudio.Metadata", code: 4, userInfo: [NSLocalizedDescriptionKey: "Экспорт M4A metadata не завершён"])
            try? fm.removeItem(at: tempURL)
            throw error
        }
        do {
            _ = try fm.replaceItemAt(sourceURL, withItemAt: tempURL, backupItemName: nil, options: [])
        } catch {
            try? fm.removeItem(at: tempURL)
            throw error
        }
    }
'''
s = s[:start] + new_handoff + s[end:]
model.write_text(s)

subprocess.run(['/usr/libexec/PlistBuddy','-c','Set :CFBundleShortVersionString 1.6.9',str(info)], check=True)
subprocess.run(['/usr/libexec/PlistBuddy','-c','Set :CFBundleVersion 27',str(info)], check=True)
print('patched Audio v1.6.9: initial service metadata embedded in M4A; no new sidecar')
