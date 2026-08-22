from pathlib import Path
import subprocess

root = Path('/tmp/wmtext119-src')
proc = root/'WearMemoryText/TextProcessor.swift'
drive = root/'WearMemoryText/TextDriveSync.swift'
content = root/'WearMemoryText/ContentView.swift'
info = root/'WearMemoryText/Info.plist'

# v1.1.9 fixes verified failures from real-device testing:
# 1) do not discard usable Apple Speech partial text on a 30s watchdog/error;
# 2) do not create duplicate Drive files on retry/missing response id;
# 3) collapse old/random pending queue entries to one stable logical upload;
# 4) keep exactly one canonical WEARMEMORY_META_V1 record when Text rewrites M4A;
# 5) read the newest embedded status when migrating v1.1.8 M4As with multiple records;
# 6) release processor state if result saving fails.

p = proc.read_text()

# Intermediate queue/processing state is already visible in the app. Rewriting a 3-minute
# M4A for those transient states adds latency and used to accumulate metadata records.
old = '''                    _ = try? self.updateSpeechMetadata(for: url, status: "queued")\n                    queue.append(TextQueueItem(\n'''
new = '''                    queue.append(TextQueueItem(\n'''
if old not in p: raise SystemExit('queued metadata write not found')
p = p.replace(old, new, 1)
old = '''            activeItemID = item.id\n            _ = try? updateSpeechMetadata(for: sourceURL, status: "processing")\n            clearDisplayedError()\n'''
new = '''            activeItemID = item.id\n            clearDisplayedError()\n'''
if old not in p: raise SystemExit('processing metadata write not found')
p = p.replace(old, new, 1)

# A transcript containing usable text is a success even when one piece only produced
# a partial result. Preserve the diagnostic as a warning instead of sending the whole
# 3-minute file to PC and throwing the recognized text away.
old = '''        guard index < pieces.count else {\n            let text = mergeTranscriptPieces(texts)\n            if warnings.isEmpty {\n                finishSuccess(item: item, sourceURL: sourceURL, text: text, warnings: [])\n            } else {\n                markNeedsPC(item: item, sourceURL: sourceURL, reason: warnings.joined(separator: " | "), partialText: text)\n            }\n            return\n        }\n'''
new = '''        guard index < pieces.count else {\n            let text = mergeTranscriptPieces(texts)\n            if !text.isEmpty || warnings.isEmpty {\n                finishSuccess(item: item, sourceURL: sourceURL, text: text, warnings: warnings)\n            } else {\n                markNeedsPC(item: item, sourceURL: sourceURL, reason: warnings.joined(separator: " | "), partialText: "")\n            }\n            return\n        }\n'''
if old not in p: raise SystemExit('recognizePieces terminal block not found')
p = p.replace(old, new, 1)

# The real iPod files showed good partial text before the old 30s watchdog fired.
# Accept that text and advance to the next piece. Retry only when the watchdog has
# produced no text at all.
old = '''                if attempt == 0 {\n                    self.publishStatus("Часть \\(index + 1): timeout · один повтор")\n                    self.recognizePiece(\n                        item: item, sourceURL: sourceURL, pieces: pieces, index: index,\n                        texts: texts, warnings: warnings, attempt: 1,\n                        bestPartial: latestText, forceOnDevice: canOnDevice ? true : false\n                    )\n                } else {\n                    let partial = self.mergeTranscriptPieces(texts + (latestText.isEmpty ? [] : [latestText]))\n                    self.markNeedsPC(item: item, sourceURL: sourceURL, reason: "Speech timeout на части \\(index + 1)/\\(pieces.count)", partialText: partial)\n                }\n'''
new = '''                if !latestText.isEmpty {\n                    self.publishStatus("Часть \\(index + 1): принимаю распознанный текст")\n                    self.recognizePieces(\n                        item: item, sourceURL: sourceURL, pieces: pieces, index: index + 1,\n                        texts: texts + [latestText],\n                        warnings: warnings + ["Часть \\(index + 1)/\\(pieces.count): принят partial после timeout"]\n                    )\n                } else if attempt == 0 {\n                    self.publishStatus("Часть \\(index + 1): timeout без текста · один повтор")\n                    self.recognizePiece(\n                        item: item, sourceURL: sourceURL, pieces: pieces, index: index,\n                        texts: texts, warnings: warnings, attempt: 1,\n                        bestPartial: "", forceOnDevice: canOnDevice ? true : false\n                    )\n                } else {\n                    self.markNeedsPC(item: item, sourceURL: sourceURL, reason: "Speech timeout без текста на части \\(index + 1)/\\(pieces.count)", partialText: self.mergeTranscriptPieces(texts))\n                }\n'''
if old not in p: raise SystemExit('Speech watchdog block not found')
p = p.replace(old, new, 1)

# Retryable Apple/Siri errors behave the same way: a non-empty partial is useful data.
old = '''                if retryable && attempt == 0 {\n                    self.publishStatus("Часть \\(index + 1): ошибка · один повтор")\n                    self.recognizePiece(\n                        item: item, sourceURL: sourceURL, pieces: pieces, index: index,\n                        texts: texts, warnings: warnings, attempt: 1,\n                        bestPartial: latestText, forceOnDevice: canOnDevice ? true : false\n                    )\n                    return\n                }\n\n                let partial = self.mergeTranscriptPieces(texts + (latestText.isEmpty ? [] : [latestText]))\n                self.markNeedsPC(item: item, sourceURL: sourceURL, reason: diagnostic, partialText: partial)\n'''
new = '''                if retryable && !latestText.isEmpty {\n                    self.publishStatus("Часть \\(index + 1): принимаю partial после ошибки")\n                    self.recognizePieces(\n                        item: item, sourceURL: sourceURL, pieces: pieces, index: index + 1,\n                        texts: texts + [latestText], warnings: warnings + [diagnostic]\n                    )\n                    return\n                }\n\n                if retryable && attempt == 0 {\n                    self.publishStatus("Часть \\(index + 1): ошибка без текста · один повтор")\n                    self.recognizePiece(\n                        item: item, sourceURL: sourceURL, pieces: pieces, index: index,\n                        texts: texts, warnings: warnings, attempt: 1,\n                        bestPartial: "", forceOnDevice: canOnDevice ? true : false\n                    )\n                    return\n                }\n\n                let partial = self.mergeTranscriptPieces(texts + (latestText.isEmpty ? [] : [latestText]))\n                self.markNeedsPC(item: item, sourceURL: sourceURL, reason: diagnostic, partialText: partial)\n'''
if old not in p: raise SystemExit('retryable Speech error block not found')
p = p.replace(old, new, 1)

# v1.1.8 M4As may already contain queued/processing/terminal records. Select the record
# with the newest device/speech timestamp before compacting it into one canonical record.
start = p.index('    private func readWearMemoryMetadata(from sourceURL: URL) -> [String: Any] {')
end = p.index('\n    private func writeWearMemoryMetadata', start)
reader = r'''    private func readWearMemoryMetadata(from sourceURL: URL) -> [String: Any] {
        let asset = AVURLAsset(url: sourceURL)
        let iso = ISO8601DateFormatter()
        var best: [String: Any] = [:]
        var bestDate = Date.distantPast
        for item in asset.metadata {
            guard item.identifier == .quickTimeMetadataDescription,
                  let value = item.stringValue,
                  value.hasPrefix(wearMemoryMetadataPrefix) else { continue }
            let json = String(value.dropFirst(wearMemoryMetadataPrefix.count))
            guard let data = json.data(using: .utf8),
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
            let keys = ["pcUpdatedAt", "tabletUpdatedAt", "ipadUpdatedAt", "speechUpdatedAt", "exportedAt", "endedAt"]
            let candidate = keys.compactMap { key -> Date? in
                guard let text = object[key] as? String else { return nil }
                return iso.date(from: text)
            }.max() ?? Date.distantPast
            if best.isEmpty || candidate >= bestDate {
                best = object
                bestDate = candidate
            }
        }
        return best
    }
'''
p = p[:start] + reader + p[end:]

# Export from a fresh audio composition. Unlike exporting the source asset directly,
# this does not carry every old description atom forward; only the one canonical
# WEARMEMORY_META_V1 description is written to the new M4A container.
start = p.index('    private func writeWearMemoryMetadata(_ object: [String: Any], to sourceURL: URL) throws {')
end = p.index('\n    private func updateSpeechMetadata', start)
writer = r'''    private func writeWearMemoryMetadata(_ object: [String: Any], to sourceURL: URL) throws {
        let jsonData = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        guard let json = String(data: jsonData, encoding: .utf8) else {
            throw NSError(domain: "WearMemoryText.Metadata", code: 1, userInfo: [NSLocalizedDescriptionKey: "Не удалось кодировать metadata"])
        }

        let sourceAsset = AVURLAsset(url: sourceURL)
        guard let sourceTrack = sourceAsset.tracks(withMediaType: .audio).first else {
            throw NSError(domain: "WearMemoryText.Metadata", code: 2, userInfo: [NSLocalizedDescriptionKey: "В M4A нет аудиодорожки"])
        }
        let composition = AVMutableComposition()
        guard let track = composition.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid) else {
            throw NSError(domain: "WearMemoryText.Metadata", code: 3, userInfo: [NSLocalizedDescriptionKey: "Не удалось создать аудиодорожку"])
        }
        try track.insertTimeRange(CMTimeRange(start: .zero, duration: sourceAsset.duration), of: sourceTrack, at: .zero)

        let compatible = AVAssetExportSession.exportPresets(compatibleWith: composition)
        let preset = compatible.contains(AVAssetExportPresetPassthrough) ? AVAssetExportPresetPassthrough : AVAssetExportPresetAppleM4A
        guard let exporter = AVAssetExportSession(asset: composition, presetName: preset) else {
            throw NSError(domain: "WearMemoryText.Metadata", code: 4, userInfo: [NSLocalizedDescriptionKey: "Не удалось открыть M4A для metadata"])
        }
        let tempURL = sourceURL.deletingLastPathComponent().appendingPathComponent(".wmmeta-\(UUID().uuidString).m4a")
        try? fm.removeItem(at: tempURL)
        exporter.outputURL = tempURL
        exporter.outputFileType = .m4a

        let metadataItem = AVMutableMetadataItem()
        metadataItem.identifier = .quickTimeMetadataDescription
        metadataItem.value = (wearMemoryMetadataPrefix + json) as NSString
        exporter.metadata = [metadataItem]

        let semaphore = DispatchSemaphore(value: 0)
        exporter.exportAsynchronously { semaphore.signal() }
        guard semaphore.wait(timeout: .now() + 60) == .success else {
            exporter.cancelExport()
            try? fm.removeItem(at: tempURL)
            throw NSError(domain: "WearMemoryText.Metadata", code: 5, userInfo: [NSLocalizedDescriptionKey: "Timeout записи metadata в M4A"])
        }
        guard exporter.status == .completed, fm.fileExists(atPath: tempURL.path) else {
            let error = exporter.error ?? NSError(domain: "WearMemoryText.Metadata", code: 6, userInfo: [NSLocalizedDescriptionKey: "Экспорт M4A metadata не завершён"])
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
p = p[:start] + writer + p[end:]

# Persist non-fatal Speech diagnostics inside the same M4A while keeping ipadStatus=ready.
old = '            _ = try updateSpeechMetadata(for: sourceURL, status: "recognized_complete")\n'
new = '            _ = try updateSpeechMetadata(for: sourceURL, status: "recognized_complete", reason: warnings.isEmpty ? nil : warnings.joined(separator: " | "))\n'
if old not in p: raise SystemExit('success metadata call not found')
p = p.replace(old, new, 1)

# A failed save must not leave activeItemID/deadline stuck forever.
old = '''    private func finishFailure(itemID: String, message: String) {\n        var queue = loadQueue()\n'''
new = '''    private func finishFailure(itemID: String, message: String) {\n        stopFileDeadline()\n        cleanupCurrentSpeechTask()\n        if activeItemID == itemID { activeItemID = nil }\n        var queue = loadQueue()\n'''
if old not in p: raise SystemExit('finishFailure block not found')
p = p.replace(old, new, 1)
proc.write_text(p)

# Audio-tab status reader uses the same newest-record rule while old v1.1.8 M4As are migrated.
c = content.read_text()
start = c.index('    private static func readStatusMetadata(for audioURL: URL)')
end = c.index('\n    static func formatTime', start)
ui_reader = r'''    private static func readStatusMetadata(for audioURL: URL) -> (ipadStatus: String?, ipadError: String?, tabletStatus: String?, tabletError: String?, pcStatus: String?, pcError: String?) {
        let prefix = "WEARMEMORY_META_V1:"
        let asset = AVURLAsset(url: audioURL)
        let iso = ISO8601DateFormatter()
        var object: [String: Any]? = nil
        var bestDate = Date.distantPast
        for item in asset.metadata {
            guard item.identifier == .quickTimeMetadataDescription,
                  let value = item.stringValue,
                  value.hasPrefix(prefix) else { continue }
            let json = String(value.dropFirst(prefix.count))
            guard let data = json.data(using: .utf8),
                  let parsed = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
            let keys = ["pcUpdatedAt", "tabletUpdatedAt", "ipadUpdatedAt", "speechUpdatedAt", "exportedAt", "endedAt"]
            let candidate = keys.compactMap { key -> Date? in
                guard let text = parsed[key] as? String else { return nil }
                return iso.date(from: text)
            }.max() ?? Date.distantPast
            if object == nil || candidate >= bestDate {
                object = parsed
                bestDate = candidate
            }
        }
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
c = c[:start] + ui_reader + c[end:]
content.write_text(c)

# Drive: stable logical IDs + exact-name lookup make uploads idempotent.
d = drive.read_text()
old = '            queue.append(PendingItem(id: "text:\\(sourceURL.lastPathComponent):\\(UUID().uuidString)", path: sourceURL.path, folderID: Self.textFolderID, mimeType: "text/plain; charset=utf-8"))\n'
new = '            queue.append(PendingItem(id: "text:\\(sourceURL.lastPathComponent)", path: sourceURL.path, folderID: Self.textFolderID, mimeType: "text/plain; charset=utf-8"))\n'
if old not in d: raise SystemExit('random text queue id not found')
d = d.replace(old, new, 1)
old = '                id: "audio:\\(audioURL.lastPathComponent):\\(UUID().uuidString)",\n'
new = '                id: "audio:\\(audioURL.lastPathComponent)",\n'
if old not in d: raise SystemExit('random audio queue id not found')
d = d.replace(old, new, 1)

old = '''        var queue = loadQueue()\n        queue.removeAll { !fm.fileExists(atPath: $0.path) }\n        saveQueue(queue)\n'''
new = '''        var queue = normalizedPendingQueue(loadQueue())\n        queue.removeAll { !fm.fileExists(atPath: $0.path) }\n        saveQueue(queue)\n'''
if old not in d: raise SystemExit('first Drive queue load not found')
d = d.replace(old, new, 1)

old = '''                        var queue = self.loadQueue()\n                        let sanitized = queue.filter { item in\n                            if item.folderID == Self.audioFolderID {\n                                return URL(fileURLWithPath: item.path).pathExtension.lowercased() == "m4a"\n                            }\n                            return true\n                        }\n                        if sanitized.count != queue.count {\n                            self.saveQueue(sanitized)\n                            queue = sanitized\n                        }\n'''
new = '''                        let queue = self.normalizedPendingQueue(self.loadQueue())\n                        self.saveQueue(queue)\n'''
if old not in d: raise SystemExit('Drive sanitize block not found')
d = d.replace(old, new, 1)

old = '''                        if activeIDs.isEmpty, let item = queue.first {\n                            do { try self.scheduleBackgroundUpload(item: item, accessToken: token) }\n                            catch { self.setError("Google Drive: \\(error.localizedDescription)") }\n                        }\n                        self.isFlushing = false\n                        self.updatePendingCount()\n'''
new = '''                        if activeIDs.isEmpty, let item = queue.first {\n                            self.scheduleIdempotentUpload(item: item, accessToken: token)\n                            return\n                        }\n                        self.isFlushing = false\n                        self.updatePendingCount()\n'''
if old not in d: raise SystemExit('Drive scheduling block not found')
d = d.replace(old, new, 1)

old = '''        let data = try Data(contentsOf: sourceURL)\n        guard !data.isEmpty else { throw driveError("TXT пуст") }\n'''
new = '''        let data = try Data(contentsOf: sourceURL)\n        if data.isEmpty && sourceURL.pathExtension.lowercased() == "m4a" {\n            throw driveError("M4A пуст")\n        }\n'''
if old not in d: raise SystemExit('empty-file guard not found')
d = d.replace(old, new, 1)

marker = '    private func scheduleBackgroundUpload(item: PendingItem, accessToken: String) throws {\n'
helpers = r'''    private func normalizedPendingQueue(_ items: [PendingItem]) -> [PendingItem] {
        var keys: [String] = []
        var latest: [String: PendingItem] = [:]
        for item in items {
            let url = URL(fileURLWithPath: item.path)
            let folderID = item.folderID ?? Self.textFolderID
            if folderID == Self.audioFolderID && url.pathExtension.lowercased() != "m4a" { continue }
            let kind = folderID == Self.audioFolderID ? "audio" : "text"
            let key = folderID + "|" + url.lastPathComponent
            if latest[key] == nil { keys.append(key) }
            latest[key] = PendingItem(
                id: kind + ":" + url.lastPathComponent,
                path: item.path,
                folderID: folderID,
                mimeType: item.mimeType
            )
        }
        return keys.compactMap { latest[$0] }
    }

    private func scheduleIdempotentUpload(item: PendingItem, accessToken: String) {
        let sourceURL = URL(fileURLWithPath: item.path)
        let folderID = item.folderID ?? Self.textFolderID
        let mappingKey = "text.drive.remote.\(folderID).\(sourceURL.lastPathComponent)"
        if defaults.string(forKey: mappingKey) != nil {
            do { try scheduleBackgroundUpload(item: item, accessToken: accessToken) }
            catch { setError("Google Drive: \(error.localizedDescription)") }
            isFlushing = false
            updatePendingCount()
            return
        }

        findRemoteFileID(named: sourceURL.lastPathComponent, parentID: folderID, accessToken: accessToken) { [weak self] result in
            guard let self = self else { return }
            self.workQueue.async {
                switch result {
                case .failure(let error):
                    self.setError("Google Drive поиск файла: \(error.localizedDescription)")
                case .success(let remoteID):
                    if let remoteID = remoteID { self.defaults.set(remoteID, forKey: mappingKey) }
                    do { try self.scheduleBackgroundUpload(item: item, accessToken: accessToken) }
                    catch { self.setError("Google Drive: \(error.localizedDescription)") }
                }
                self.isFlushing = false
                self.updatePendingCount()
            }
        }
    }

    private func findRemoteFileID(named name: String, parentID: String, accessToken: String, completion: @escaping (Result<String?, Error>) -> Void) {
        let escaped = name.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "'", with: "\\'")
        var components = URLComponents(string: "https://www.googleapis.com/drive/v3/files")!
        components.queryItems = [
            URLQueryItem(name: "q", value: "'\(parentID)' in parents and name = '\(escaped)' and trashed = false"),
            URLQueryItem(name: "fields", value: "files(id,name,createdTime)"),
            URLQueryItem(name: "orderBy", value: "createdTime"),
            URLQueryItem(name: "pageSize", value: "100")
        ]
        guard let url = components.url else {
            completion(.failure(driveError("Не удалось создать запрос поиска Drive")))
            return
        }
        var request = URLRequest(url: url)
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        URLSession.shared.dataTask(with: request) { data, response, error in
            if let error = error { completion(.failure(error)); return }
            guard let http = response as? HTTPURLResponse, let data = data else {
                completion(.failure(self.driveError("Пустой ответ поиска Drive")))
                return
            }
            guard (200..<300).contains(http.statusCode) else {
                let text = String(data: data, encoding: .utf8) ?? "HTTP \(http.statusCode)"
                completion(.failure(self.driveError(text)))
                return
            }
            guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let files = object["files"] as? [[String: Any]] else {
                completion(.failure(self.driveError("Некорректный ответ поиска Drive")))
                return
            }
            completion(.success(files.compactMap { $0["id"] as? String }.first))
        }.resume()
    }

'''
if marker not in d: raise SystemExit('scheduleBackgroundUpload marker not found')
d = d.replace(marker, helpers + marker, 1)

# HTTP 2xx means the create itself succeeded. Missing response JSON must never trigger
# another POST. Save the file id when it is available (TXT or M4A); exact-name lookup
# recovers the mapping on a later enqueue if the background response body was empty.
old = '''        if descriptor.operation == .createText && descriptor.itemID.hasPrefix("text:") {\n            guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],\n                  let remoteID = json["id"] as? String, !remoteID.isEmpty else {\n                setError("Google Drive не вернул file id для TXT")\n                flushQueue(); return\n            }\n            defaults.set(remoteID, forKey: descriptor.mappingKey)\n        }\n'''
new = '''        if descriptor.operation == .createText,\n           let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],\n           let remoteID = json["id"] as? String, !remoteID.isEmpty {\n            defaults.set(remoteID, forKey: descriptor.mappingKey)\n        }\n'''
if old not in d: raise SystemExit('create response id block not found')
d = d.replace(old, new, 1)
drive.write_text(d)

subprocess.run(['/usr/libexec/PlistBuddy','-c','Set :CFBundleShortVersionString 1.1.9',str(info)], check=True)
subprocess.run(['/usr/libexec/PlistBuddy','-c','Set :CFBundleVersion 19',str(info)], check=True)

print('patched v1.1.9: Speech partial acceptance, Drive idempotency, metadata compaction, queue safety')
