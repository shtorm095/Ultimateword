from pathlib import Path
import subprocess

root = Path('/tmp/wmtext118-src')
proc = root/'WearMemoryText/TextProcessor.swift'
drive = root/'WearMemoryText/TextDriveSync.swift'
model = root/'WearMemoryText/TextAppModel.swift'
content = root/'WearMemoryText/ContentView.swift'
info = root/'WearMemoryText/Info.plist'

# v1.1.8 storage contract:
#   Audio Hören -> M4A only.
#   Audio Lesen -> one TXT for each source M4A (same basename).
#   WearMemory service state is embedded inside the M4A QuickTime metadata.
#   No new .meta.json is created or uploaded. Old sidecars are migration input only.

p = proc.read_text()

# One terminal audio callback is used for both iPad-ready and iPad-not-ready files.
p = p.replace('    var onNeedsPC: ((URL, URL) -> Void)?\n', '    var onAudioReady: ((URL) -> Void)?\n', 1)
if 'var onAudioReady: ((URL) -> Void)?' not in p:
    raise SystemExit('onAudioReady callback insertion failed')

start = p.index('    private func updateSpeechSidecar(')
end = p.index('    private func hasTerminalIPadResult', start)
embedded_block = r'''    private let wearMemoryMetadataPrefix = "WEARMEMORY_META_V1:"

    private func readWearMemoryMetadata(from sourceURL: URL) -> [String: Any] {
        let asset = AVURLAsset(url: sourceURL)
        for item in asset.metadata.reversed() {
            guard item.identifier == .quickTimeMetadataDescription,
                  let value = item.stringValue,
                  value.hasPrefix(wearMemoryMetadataPrefix) else { continue }
            let json = String(value.dropFirst(wearMemoryMetadataPrefix.count))
            guard let data = json.data(using: .utf8),
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
            return object
        }
        return [:]
    }

    private func writeWearMemoryMetadata(_ object: [String: Any], to sourceURL: URL) throws {
        let jsonData = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        guard let json = String(data: jsonData, encoding: .utf8) else {
            throw NSError(domain: "WearMemoryText.Metadata", code: 1, userInfo: [NSLocalizedDescriptionKey: "Не удалось кодировать metadata"])
        }

        let asset = AVURLAsset(url: sourceURL)
        let compatible = AVAssetExportSession.exportPresets(compatibleWith: asset)
        let preset = compatible.contains(AVAssetExportPresetPassthrough) ? AVAssetExportPresetPassthrough : AVAssetExportPresetAppleM4A
        guard let exporter = AVAssetExportSession(asset: asset, presetName: preset) else {
            throw NSError(domain: "WearMemoryText.Metadata", code: 2, userInfo: [NSLocalizedDescriptionKey: "Не удалось открыть M4A для metadata"])
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
            throw NSError(domain: "WearMemoryText.Metadata", code: 3, userInfo: [NSLocalizedDescriptionKey: "Timeout записи metadata в M4A"])
        }
        guard exporter.status == .completed, fm.fileExists(atPath: tempURL.path) else {
            let error = exporter.error ?? NSError(domain: "WearMemoryText.Metadata", code: 4, userInfo: [NSLocalizedDescriptionKey: "Экспорт M4A metadata не завершён"])
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

    private func updateSpeechMetadata(for sourceURL: URL, status: String, reason: String? = nil, partialText: String? = nil) throws -> URL {
        var object = readWearMemoryMetadata(from: sourceURL)
        let iso = ISO8601DateFormatter()
        let now = iso.string(from: Date())
        object["wearMemoryMetadataVersion"] = 1
        object["recordingId"] = sourceURL.deletingPathExtension().lastPathComponent
        object["sourceFileName"] = sourceURL.lastPathComponent
        object["speechStatus"] = status
        object["speechUpdatedAt"] = now
        object["language"] = language.rawValue
        if let reason = reason { object["speechReason"] = reason } else { object.removeValue(forKey: "speechReason") }
        if let partialText = partialText, !partialText.isEmpty { object["partialText"] = partialText }
        else { object.removeValue(forKey: "partialText") }

        // Text writes only the iPad status. Tablette/PC fields, if already present,
        // remain untouched in the same embedded metadata object.
        switch status {
        case "queued":
            object["ipadStatus"] = "queued"
            object["ipadUpdatedAt"] = now
            object.removeValue(forKey: "ipadErrorStage")
            object.removeValue(forKey: "ipadErrorMessage")
            object.removeValue(forKey: "ipadErrorAt")
        case "processing":
            object["ipadStatus"] = "processing"
            object["ipadUpdatedAt"] = now
            object.removeValue(forKey: "ipadErrorStage")
            object.removeValue(forKey: "ipadErrorMessage")
            object.removeValue(forKey: "ipadErrorAt")
        case "recognized_complete":
            object["ipadStatus"] = "ready"
            object["ipadUpdatedAt"] = now
            object.removeValue(forKey: "ipadErrorStage")
            object.removeValue(forKey: "ipadErrorMessage")
            object.removeValue(forKey: "ipadErrorAt")
        case "needs_pc":
            object["ipadStatus"] = "not_ready"
            object["ipadUpdatedAt"] = now
            object["ipadErrorStage"] = "speech"
            object["ipadErrorMessage"] = reason ?? "Неизвестная ошибка распознавания"
            object["ipadErrorAt"] = now
        default:
            break
        }

        try writeWearMemoryMetadata(object, to: sourceURL)
        return sourceURL
    }

'''
p = p[:start] + embedded_block + p[end:]

# Terminal state now comes from the M4A itself. Legacy sidecars are imported once,
# embedded, and removed locally; they are never uploaded.
start = p.index('    private func hasTerminalIPadResult')
end = p.index('\n    private func migrateLegacyIPadStatusIfNeeded', start)
has_terminal = r'''    private func hasTerminalIPadResult(for sourceURL: URL) -> Bool {
        let object = readWearMemoryMetadata(from: sourceURL)
        if let status = object["ipadStatus"] as? String,
           status == "ready" || status == "not_ready" { return true }
        if let legacy = object["speechStatus"] as? String,
           legacy == "recognized_complete" || legacy == "needs_pc" { return true }
        return false
    }
'''
p = p[:start] + has_terminal + p[end:]

start = p.index('    private func migrateLegacyIPadStatusIfNeeded')
# this helper is immediately before proc.write_text in v1.1.4-generated source only conceptually;
# in final Swift source the next declaration is finishSuccess/start deadline depending patch order.
# Find the next private function after this declaration.
next_pos = p.find('\n    private func ', start + len('    private func migrateLegacyIPadStatusIfNeeded'))
if next_pos == -1:
    raise SystemExit('cannot find end of migrateLegacyIPadStatusIfNeeded')
legacy_migration = r'''    private func migrateLegacyIPadStatusIfNeeded(for sourceURL: URL) {
        var object = readWearMemoryMetadata(from: sourceURL)
        var changed = false

        // Import v1.1.7-and-older local sidecar data once, then remove that sidecar.
        let legacyURL = sourceURL.deletingPathExtension().appendingPathExtension("meta.json")
        if let data = try? Data(contentsOf: legacyURL),
           let legacy = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            for (key, value) in legacy where object[key] == nil {
                object[key] = value
                changed = true
            }
        }

        let iso = ISO8601DateFormatter()
        let now = iso.string(from: Date())
        object["wearMemoryMetadataVersion"] = 1
        object["recordingId"] = sourceURL.deletingPathExtension().lastPathComponent
        object["sourceFileName"] = sourceURL.lastPathComponent

        if object["ipadStatus"] == nil, let legacy = object["speechStatus"] as? String {
            switch legacy {
            case "recognized_complete":
                object["ipadStatus"] = "ready"
                object["ipadUpdatedAt"] = now
                changed = true
            case "needs_pc":
                object["ipadStatus"] = "not_ready"
                object["ipadUpdatedAt"] = now
                object["ipadErrorStage"] = "speech"
                object["ipadErrorMessage"] = (object["speechReason"] as? String) ?? "Неизвестная ошибка распознавания"
                object["ipadErrorAt"] = (object["speechUpdatedAt"] as? String) ?? now
                changed = true
            case "pending_ipod":
                object["ipadStatus"] = "queued"
                object["ipadUpdatedAt"] = now
                changed = true
            default:
                break
            }
        }

        if changed || fm.fileExists(atPath: legacyURL.path) {
            if (try? writeWearMemoryMetadata(object, to: sourceURL)) != nil {
                try? fm.removeItem(at: legacyURL)
            }
        }
    }
'''
p = p[:start] + legacy_migration + p[next_pos:]

# Rename all remaining call sites from sidecar terminology to the embedded-M4A implementation.
p = p.replace('updateSpeechSidecar', 'updateSpeechMetadata')

# needs_pc: finish the embedded metadata first, then queue this M4A itself for Drive.
p = p.replace('            let metaURL = try updateSpeechMetadata(for: sourceURL, status: "needs_pc", reason: reason, partialText: partialText)\n',
              '            _ = try updateSpeechMetadata(for: sourceURL, status: "needs_pc", reason: reason, partialText: partialText)\n', 1)
p = p.replace('                self.statusText = "needs_pc · передано на компьютер"\n                self.onStateChanged?()\n                self.onNeedsPC?(sourceURL, metaURL)\n',
              '                self.statusText = "Не готов на iPad"\n                self.onStateChanged?()\n                self.onAudioReady?(sourceURL)\n', 1)
if 'onNeedsPC?' in p:
    raise SystemExit('old onNeedsPC callback remains')

# Successful recognition creates ONE TXT for THIS M4A, with the same basename.
p = p.replace('            let journal = try rebuildDailyJournal(for: metadata.startedAt)\n',
              '            let transcriptFile = try writeSegmentText(item: item, text: text)\n', 1)
p = p.replace('                self.onStateChanged?()\n                self.onJournalUpdated?(journal)\n',
              '                self.onStateChanged?()\n                self.onAudioReady?(sourceURL)\n                self.onJournalUpdated?(transcriptFile)\n', 1)

# Add the per-segment TXT writer. Keep the older daily-journal reader for backward-compatible UI only.
marker = '    private func rebuildDailyJournal(for date: Date) throws -> URL {\n'
segment_writer = r'''    private func writeSegmentText(item: TextQueueItem, text: String) throws -> URL {
        try ensureDirectories()
        let url = journalsDirectory.appendingPathComponent(item.id + ".txt")
        let clean = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let body = clean.isEmpty ? "" : clean + "\n"
        guard let data = body.data(using: .utf8) else {
            throw NSError(domain: "WearMemoryText.Text", code: 1, userInfo: [NSLocalizedDescriptionKey: "Не удалось создать TXT"])
        }
        try data.write(to: url, options: .atomic)
        return url
    }

'''
if marker not in p:
    raise SystemExit('rebuildDailyJournal marker not found')
p = p.replace(marker, segment_writer + marker, 1)

# Timestamps now come from embedded M4A metadata. Old local sidecar is fallback-only migration support.
start = p.index('    private func metadataForAudio(_ url: URL) throws -> AudioBridgeMetadata {')
end = p.index('\n    private func writeSegmentText', start)
metadata_for_audio = r'''    private func metadataForAudio(_ url: URL) throws -> AudioBridgeMetadata {
        let iso = ISO8601DateFormatter()
        let object = readWearMemoryMetadata(from: url)
        if let startedText = object["startedAt"] as? String,
           let endedText = object["endedAt"] as? String,
           let started = iso.date(from: startedText),
           let ended = iso.date(from: endedText) {
            let exported = (object["exportedAt"] as? String).flatMap { iso.date(from: $0) }
            return AudioBridgeMetadata(
                bridgeVersion: object["bridgeVersion"] as? Int,
                sourceFileName: (object["sourceFileName"] as? String) ?? url.lastPathComponent,
                startedAt: started,
                endedAt: ended,
                exportedAt: exported
            )
        }

        // Compatibility only: pre-v1.1.8 Audio may still have produced a local sidecar.
        let legacySidecar = url.deletingPathExtension().appendingPathExtension("meta.json")
        if fm.fileExists(atPath: legacySidecar.path) {
            return try decoder.decode(AudioBridgeMetadata.self, from: Data(contentsOf: legacySidecar))
        }

        let values = try url.resourceValues(forKeys: [.creationDateKey])
        let created = values.creationDate ?? Date()
        let asset = AVURLAsset(url: url)
        let duration = CMTimeGetSeconds(asset.duration)
        return AudioBridgeMetadata(bridgeVersion: nil, sourceFileName: url.lastPathComponent, startedAt: created, endedAt: created.addingTimeInterval(duration.isFinite ? max(0, duration) : 0), exportedAt: nil)
    }
'''
p = p[:start] + metadata_for_audio + p[end:]

proc.write_text(p)

# AppModel: all terminal M4A files go to Audio Hören. No metadata file callback exists anymore.
m = model.read_text()
old_model_cb = '''        processor.onNeedsPC = { [weak self] audioURL, metadataURL in\n            self?.drive.enqueueAudioForPC(audioURL, metadataURL: metadataURL)\n        }\n'''
new_model_cb = '''        processor.onAudioReady = { [weak self] audioURL in\n            self?.drive.enqueueAudio(audioURL)\n        }\n'''
if old_model_cb not in m:
    raise SystemExit('TextAppModel old onNeedsPC callback not found')
m = m.replace(old_model_cb, new_model_cb, 1)
model.write_text(m)

# Drive: Audio Hören accepts ONLY M4A. No JSON/metadata queue item is created.
d = drive.read_text()
start = d.index('    func enqueueAudioForPC(')
end = d.index('    func flushQueue() {', start)
new_audio_queue = r'''    func enqueueAudio(_ audioURL: URL) {
        workQueue.async {
            guard self.fm.fileExists(atPath: audioURL.path), audioURL.pathExtension.lowercased() == "m4a" else {
                self.setError("Audio Hören: M4A не найден")
                return
            }
            var queue = self.loadQueue()
            queue.removeAll { item in
                item.folderID == Self.audioFolderID && URL(fileURLWithPath: item.path).lastPathComponent == audioURL.lastPathComponent
            }
            queue.append(PendingItem(
                id: "audio:\(audioURL.lastPathComponent):\(UUID().uuidString)",
                path: audioURL.path,
                folderID: Self.audioFolderID,
                mimeType: "audio/mp4"
            ))
            self.saveQueue(queue)
            self.flushQueueLocked()
        }
    }

'''
d = d[:start] + new_audio_queue + d[end:]

# Purge old pending .meta.json/non-M4A items that earlier builds may have queued for Audio Hören.
old_serial = '''                        let activeIDs = Set(tasks.compactMap { self.descriptor(for: $0)?.itemID })\n                        let queue = self.loadQueue()\n                        if activeIDs.isEmpty, let item = queue.first {\n'''
new_serial = '''                        let activeIDs = Set(tasks.compactMap { self.descriptor(for: $0)?.itemID })\n                        var queue = self.loadQueue()\n                        let sanitized = queue.filter { item in\n                            if item.folderID == Self.audioFolderID {\n                                return URL(fileURLWithPath: item.path).pathExtension.lowercased() == "m4a"\n                            }\n                            return true\n                        }\n                        if sanitized.count != queue.count {\n                            self.saveQueue(sanitized)\n                            queue = sanitized\n                        }\n                        if activeIDs.isEmpty, let item = queue.first {\n'''
if old_serial not in d:
    raise SystemExit('serialized Drive queue block not found')
d = d.replace(old_serial, new_serial, 1)
if 'enqueueAudioForPC' in d or 'metadataURL' in d:
    raise SystemExit('old metadata upload API remains in TextDriveSync')
drive.write_text(d)

# Audio-tab status display reads service state from the embedded M4A metadata.
c = content.read_text()
if 'import AVFoundation\n' not in c:
    c = c.replace('import SwiftUI\n', 'import SwiftUI\nimport AVFoundation\n', 1)
start = c.index('    private static func readStatusMetadata(for audioURL: URL)')
end = c.index('    static func formatTime(_ value: TimeInterval) -> String {', start)
read_status = r'''    private static func readStatusMetadata(for audioURL: URL) -> (ipadStatus: String?, ipadError: String?, tabletStatus: String?, tabletError: String?, pcStatus: String?, pcError: String?) {
        let prefix = "WEARMEMORY_META_V1:"
        let asset = AVURLAsset(url: audioURL)
        var object: [String: Any]? = nil
        for item in asset.metadata.reversed() {
            guard item.identifier == .quickTimeMetadataDescription,
                  let value = item.stringValue,
                  value.hasPrefix(prefix) else { continue }
            let json = String(value.dropFirst(prefix.count))
            if let data = json.data(using: .utf8),
               let parsed = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                object = parsed
                break
            }
        }

        // Compatibility display for a pre-v1.1.8 local file until migration runs.
        if object == nil {
            let legacyURL = audioURL.deletingPathExtension().appendingPathExtension("meta.json")
            if let data = try? Data(contentsOf: legacyURL),
               let parsed = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                object = parsed
            }
        }
        guard let object = object else { return (nil, nil, nil, nil, nil, nil) }

        var ipadStatus = object["ipadStatus"] as? String
        if ipadStatus == nil, let legacy = object["speechStatus"] as? String {
            if legacy == "recognized_complete" { ipadStatus = "ready" }
            if legacy == "needs_pc" { ipadStatus = "not_ready" }
        }
        let ipadError = (object["ipadErrorMessage"] as? String) ?? (object["speechReason"] as? String)
        let tabletStatus = object["tabletStatus"] as? String
        let tabletError = object["tabletErrorMessage"] as? String
        let pcStatus = object["pcStatus"] as? String
        let pcError = object["pcErrorMessage"] as? String
        return (ipadStatus, ipadError, tabletStatus, tabletError, pcStatus, pcError)
    }

'''
c = c[:start] + read_status + c[end:]
content.write_text(c)

subprocess.run(['/usr/libexec/PlistBuddy','-c','Set :CFBundleShortVersionString 1.1.8',str(info)], check=True)
subprocess.run(['/usr/libexec/PlistBuddy','-c','Set :CFBundleVersion 18',str(info)], check=True)

print('patched v1.1.8: M4A-only Audio Hören, per-fragment TXT, embedded service metadata')
