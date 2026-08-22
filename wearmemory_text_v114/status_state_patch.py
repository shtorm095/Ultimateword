from pathlib import Path
import subprocess

root = Path('/tmp/wmtext114-src')
proc = root/'WearMemoryText/TextProcessor.swift'
content = root/'WearMemoryText/ContentView.swift'
info = root/'WearMemoryText/Info.plist'

# --- TextProcessor: persistent per-file device status and terminal-state queue filtering. ---
s = proc.read_text()

old_discovery = '''                for url in files {\n                    let key = url.deletingPathExtension().lastPathComponent\n                    let size = (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0\n                    guard size > 0, !results.contains(key), !queue.contains(where: { $0.sourceFileName == url.lastPathComponent }) else { continue }\n                    queue.append(TextQueueItem(\n                        id: key,\n                        sourceFileName: url.lastPathComponent,\n                        state: .queued,\n                        attempts: 0,\n                        lastError: nil,\n                        nextRetryAt: nil,\n                        discoveredAt: Date()\n                    ))\n                }\n                queue.removeAll { item in\n                    let url = inbox.appendingPathComponent(item.sourceFileName)\n                    return !self.fm.fileExists(atPath: url.path) && !results.contains(item.id)\n                }\n'''
new_discovery = '''                // A stale .processing state can survive an app restart. Resume it as queued.\n                if activeItemID == nil {\n                    for index in queue.indices where queue[index].state == .processing {\n                        queue[index].state = .queued\n                        queue[index].nextRetryAt = nil\n                    }\n                }\n\n                for url in files {\n                    let key = url.deletingPathExtension().lastPathComponent\n                    let size = (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0\n\n                    // Upgrade v1.1.3 sidecars to the explicit iPad status model.\n                    self.migrateLegacyIPadStatusIfNeeded(for: url)\n                    if results.contains(key) && !self.hasTerminalIPadResult(for: url) {\n                        _ = try? self.updateSpeechSidecar(for: url, status: "recognized_complete")\n                    }\n\n                    guard size > 0,\n                          !self.hasTerminalIPadResult(for: url),\n                          !results.contains(key),\n                          !queue.contains(where: { $0.sourceFileName == url.lastPathComponent }) else { continue }\n\n                    _ = try? self.updateSpeechSidecar(for: url, status: "queued")\n                    queue.append(TextQueueItem(\n                        id: key,\n                        sourceFileName: url.lastPathComponent,\n                        state: .queued,\n                        attempts: 0,\n                        lastError: nil,\n                        nextRetryAt: nil,\n                        discoveredAt: Date()\n                    ))\n                }\n\n                // Terminal files stay in AudioInbox for playback/24h retention, but they must\n                // never return to the Speech queue.\n                queue.removeAll { item in\n                    let url = inbox.appendingPathComponent(item.sourceFileName)\n                    if self.hasTerminalIPadResult(for: url) { return true }\n                    return !self.fm.fileExists(atPath: url.path) && !results.contains(item.id)\n                }\n'''
if old_discovery not in s:
    raise SystemExit('refreshQueue discovery block not found')
s = s.replace(old_discovery, new_discovery, 1)

old_process = '''            setProcessingLocked(true)\n            activeItemID = item.id\n            startFileDeadline(item: item, sourceURL: sourceURL)\n            publishStatus("Распознаю \\(item.sourceFileName) · лимит 3 мин")\n'''
new_process = '''            setProcessingLocked(true)\n            activeItemID = item.id\n            _ = try? updateSpeechSidecar(for: sourceURL, status: "processing")\n            startFileDeadline(item: item, sourceURL: sourceURL)\n            publishStatus("Распознаю \\(item.sourceFileName) · лимит 3 мин")\n'''
if old_process not in s:
    raise SystemExit('process start block not found')
s = s.replace(old_process, new_process, 1)

old_sidecar = r'''    private func updateSpeechSidecar(for sourceURL: URL, status: String, reason: String? = nil, partialText: String? = nil) throws -> URL {
        let metaURL = sourceURL.deletingPathExtension().appendingPathExtension("meta.json")
        var object: [String: Any] = [:]
        if let data = try? Data(contentsOf: metaURL),
           let existing = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            object = existing
        }
        let iso = ISO8601DateFormatter()
        object["sourceFileName"] = sourceURL.lastPathComponent
        object["speechStatus"] = status
        object["speechUpdatedAt"] = iso.string(from: Date())
        object["language"] = language.rawValue
        if let reason = reason { object["speechReason"] = reason } else { object.removeValue(forKey: "speechReason") }
        if let partialText = partialText, !partialText.isEmpty { object["partialText"] = partialText }
        else { object.removeValue(forKey: "partialText") }
        let data = try JSONSerialization.data(withJSONObject: object, options: [.prettyPrinted, .sortedKeys])
        try data.write(to: metaURL, options: .atomic)
        return metaURL
    }
'''
new_sidecar = r'''    private func updateSpeechSidecar(for sourceURL: URL, status: String, reason: String? = nil, partialText: String? = nil) throws -> URL {
        let metaURL = sourceURL.deletingPathExtension().appendingPathExtension("meta.json")
        var object: [String: Any] = [:]
        if let data = try? Data(contentsOf: metaURL),
           let existing = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            object = existing
        }
        let iso = ISO8601DateFormatter()
        let now = iso.string(from: Date())
        object["sourceFileName"] = sourceURL.lastPathComponent
        object["speechStatus"] = status
        object["speechUpdatedAt"] = now
        object["language"] = language.rawValue
        if let reason = reason { object["speechReason"] = reason } else { object.removeValue(forKey: "speechReason") }
        if let partialText = partialText, !partialText.isEmpty { object["partialText"] = partialText }
        else { object.removeValue(forKey: "partialText") }

        // Explicit iPad state. The iPad application NEVER writes pcStatus/pcError*.
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

        let data = try JSONSerialization.data(withJSONObject: object, options: [.prettyPrinted, .sortedKeys])
        try data.write(to: metaURL, options: .atomic)
        return metaURL
    }

    private func hasTerminalIPadResult(for sourceURL: URL) -> Bool {
        let metaURL = sourceURL.deletingPathExtension().appendingPathExtension("meta.json")
        guard let data = try? Data(contentsOf: metaURL),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return false }
        if let status = object["ipadStatus"] as? String,
           status == "ready" || status == "not_ready" { return true }
        // Compatibility with v1.1.3 metadata.
        if let legacy = object["speechStatus"] as? String,
           legacy == "recognized_complete" || legacy == "needs_pc" { return true }
        return false
    }

    private func migrateLegacyIPadStatusIfNeeded(for sourceURL: URL) {
        let metaURL = sourceURL.deletingPathExtension().appendingPathExtension("meta.json")
        guard let data = try? Data(contentsOf: metaURL),
              var object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              object["ipadStatus"] == nil,
              let legacy = object["speechStatus"] as? String else { return }
        let iso = ISO8601DateFormatter()
        let now = iso.string(from: Date())
        switch legacy {
        case "recognized_complete":
            object["ipadStatus"] = "ready"
            object["ipadUpdatedAt"] = now
        case "needs_pc":
            object["ipadStatus"] = "not_ready"
            object["ipadUpdatedAt"] = now
            object["ipadErrorStage"] = "speech"
            object["ipadErrorMessage"] = (object["speechReason"] as? String) ?? "Неизвестная ошибка распознавания"
            object["ipadErrorAt"] = (object["speechUpdatedAt"] as? String) ?? now
        default:
            return
        }
        if let updated = try? JSONSerialization.data(withJSONObject: object, options: [.prettyPrinted, .sortedKeys]) {
            try? updated.write(to: metaURL, options: .atomic)
        }
    }
'''
if old_sidecar not in s:
    raise SystemExit('updateSpeechSidecar block not found')
s = s.replace(old_sidecar, new_sidecar, 1)

proc.write_text(s)

# --- Audio tab: show iPad result, optional PC result, and error details. ---
c = content.read_text()

old_status_ui = '''                                    HStack(spacing: 8) {\n                                        Text(item.durationText)\n                                        Text(item.sizeText)\n                                    }\n                                    .font(.caption2)\n                                    .foregroundColor(.secondary)\n'''
new_status_ui = '''                                    HStack(spacing: 8) {\n                                        Text(item.durationText)\n                                        Text(item.sizeText)\n                                    }\n                                    .font(.caption2)\n                                    .foregroundColor(.secondary)\n                                    Text(item.ipadStatusText)\n                                        .font(.caption.weight(.semibold))\n                                        .foregroundColor(item.ipadStatus == "ready" ? .green : (item.ipadStatus == "not_ready" ? .orange : .secondary))\n                                    if let pc = item.pcStatusText {\n                                        Text(pc)\n                                            .font(.caption.weight(.semibold))\n                                            .foregroundColor(item.pcStatus == "ready" ? .green : .orange)\n                                    }\n                                    if let error = item.visibleError, !error.isEmpty {\n                                        Text(error)\n                                            .font(.caption2)\n                                            .foregroundColor(.orange)\n                                            .lineLimit(4)\n                                    }\n'''
if old_status_ui not in c:
    raise SystemExit('audio status UI block not found')
c = c.replace(old_status_ui, new_status_ui, 1)

old_struct = r'''private struct AudioInboxFile: Identifiable {
    let id: String
    let url: URL
    let duration: TimeInterval
    let bytes: Int64

    var durationText: String { AudioInboxPlayer.formatTime(duration) }
    var sizeText: String { ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file) }
}
'''
new_struct = r'''private struct AudioInboxFile: Identifiable {
    let id: String
    let url: URL
    let duration: TimeInterval
    let bytes: Int64
    let ipadStatus: String?
    let ipadError: String?
    let pcStatus: String?
    let pcError: String?

    var durationText: String { AudioInboxPlayer.formatTime(duration) }
    var sizeText: String { ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file) }

    var ipadStatusText: String {
        switch ipadStatus {
        case "ready": return "Готов на iPad"
        case "not_ready": return "Не готов на iPad"
        case "processing": return "Обрабатывается на iPad"
        case "queued": return "Ожидает обработки на iPad"
        default: return "Статус iPad не определён"
        }
    }

    var pcStatusText: String? {
        switch pcStatus {
        case "ready": return "Готов на ПК"
        case "not_ready": return "Не готов на ПК"
        default: return nil
        }
    }

    var visibleError: String? {
        if ipadStatus == "not_ready", let ipadError = ipadError { return "iPad: \(ipadError)" }
        if pcStatus == "not_ready", let pcError = pcError { return "ПК: \(pcError)" }
        return nil
    }
}
'''
if old_struct not in c:
    raise SystemExit('AudioInboxFile struct not found')
c = c.replace(old_struct, new_struct, 1)

old_map = '''                return AudioInboxFile(id: url.path, url: url, duration: d, bytes: bytes)\n'''
new_map = '''                let status = Self.readStatusMetadata(for: url)\n                return AudioInboxFile(\n                    id: url.path, url: url, duration: d, bytes: bytes,\n                    ipadStatus: status.ipadStatus, ipadError: status.ipadError,\n                    pcStatus: status.pcStatus, pcError: status.pcError\n                )\n'''
if old_map not in c:
    raise SystemExit('AudioInboxFile map not found')
c = c.replace(old_map, new_map, 1)

format_marker = '''    static func formatTime(_ value: TimeInterval) -> String {\n'''
metadata_helper = r'''    private static func readStatusMetadata(for audioURL: URL) -> (ipadStatus: String?, ipadError: String?, pcStatus: String?, pcError: String?) {
        let metaURL = audioURL.deletingPathExtension().appendingPathExtension("meta.json")
        guard let data = try? Data(contentsOf: metaURL),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return (nil, nil, nil, nil)
        }

        var ipadStatus = object["ipadStatus"] as? String
        if ipadStatus == nil, let legacy = object["speechStatus"] as? String {
            if legacy == "recognized_complete" { ipadStatus = "ready" }
            if legacy == "needs_pc" { ipadStatus = "not_ready" }
        }
        let ipadError = (object["ipadErrorMessage"] as? String) ?? (object["speechReason"] as? String)
        // pcStatus is read-only in the iPad app. It is written later by the computer.
        let pcStatus = object["pcStatus"] as? String
        let pcError = object["pcErrorMessage"] as? String
        return (ipadStatus, ipadError, pcStatus, pcError)
    }

'''
if format_marker not in c:
    raise SystemExit('formatTime marker not found')
c = c.replace(format_marker, metadata_helper + format_marker, 1)
content.write_text(c)

# Version bump only for this status build.
subprocess.run(['/usr/libexec/PlistBuddy','-c','Set :CFBundleShortVersionString 1.1.4',str(info)], check=True)
subprocess.run(['/usr/libexec/PlistBuddy','-c','Set :CFBundleVersion 14',str(info)], check=True)

print('patched v1.1.4 status state machine')
