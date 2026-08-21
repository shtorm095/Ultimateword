from pathlib import Path
root=Path('WearMemoryText')
proc=root/'TextProcessor.swift'
model=root/'TextAppModel.swift'
drive=root/'TextDriveSync.swift'
models=root/'Models.swift'

s=proc.read_text()
s=s.replace('''    var onJournalUpdated: ((URL) -> Void)?\n    var onStateChanged: (() -> Void)?\n''','''    var onJournalUpdated: ((URL) -> Void)?\n    var onNeedsPC: ((URL, URL) -> Void)?\n    var onStateChanged: (() -> Void)?\n''',1)
s=s.replace('''    private var retryWorkItem: DispatchWorkItem?\n''','''    private var retryWorkItem: DispatchWorkItem?\n    private var fileDeadlineWorkItem: DispatchWorkItem?\n    private var activeItemID: String?\n    private let maxFileProcessingSeconds: TimeInterval = 180\n''',1)
s=s.replace('''    deinit { currentTask?.cancel(); currentTask = nil; currentRecognizer = nil; currentRequest = nil; retryWorkItem?.cancel() }\n''','''    deinit { currentTask?.cancel(); currentTask = nil; currentRecognizer = nil; currentRequest = nil; retryWorkItem?.cancel(); fileDeadlineWorkItem?.cancel() }\n''',1)

old='''            setProcessingLocked(true)\n            publishStatus("Распознаю \\(item.sourceFileName)")\n            splitIntoPieces(sourceURL) { [weak self] result in\n'''
new='''            setProcessingLocked(true)\n            activeItemID = item.id\n            startFileDeadline(item: item, sourceURL: sourceURL)\n            publishStatus("Распознаю \\(item.sourceFileName) · лимит 3 мин")\n            splitIntoPieces(sourceURL) { [weak self] result in\n'''
if old not in s: raise SystemExit('process start not found')
s=s.replace(old,new,1)

old='''        // Primary recognition uses 60-second windows to preserve linguistic context.\n        // Adjacent windows overlap by 5 seconds so words crossing a boundary are not lost.\n        // A failed long window is adaptively split to ~30-second windows below.\n        var ranges: [(Double, Double)] = []\n        var start = 0.0\n        let primaryDuration = 60.0\n        let primaryOverlap = 5.0\n        let primaryStep = primaryDuration - primaryOverlap\n'''
new='''        // Hybrid mode: moderate chunks preserve context without flooding Apple Speech.\n        // A 2-second overlap protects words crossing chunk boundaries.\n        var ranges: [(Double, Double)] = []\n        var start = 0.0\n        let primaryDuration = 50.0\n        let primaryOverlap = 2.0\n        let primaryStep = primaryDuration - primaryOverlap\n'''
if old not in s: raise SystemExit('segmentation not found')
s=s.replace(old,new,1)

start=s.index('    private func recognizePiece(\n')
end=s.index('    private func audioDuration(_ url: URL) -> Double {', start)
newfunc=r'''    private func recognizePiece(
        item: TextQueueItem,
        sourceURL: URL,
        pieces: [URL],
        index: Int,
        texts: [String],
        warnings: [String],
        attempt: Int,
        bestPartial: String,
        forceOnDevice: Bool? = nil
    ) {
        guard activeItemID == item.id else { return }
        guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: language.rawValue)) else {
            markNeedsPC(item: item, sourceURL: sourceURL, reason: "Язык \(language.rawValue) недоступен", partialText: mergeTranscriptPieces(texts))
            return
        }
        guard recognizer.isAvailable else {
            markNeedsPC(item: item, sourceURL: sourceURL, reason: "Apple Speech сейчас недоступен", partialText: mergeTranscriptPieces(texts))
            return
        }

        cleanupCurrentSpeechTask()
        currentRecognizer = recognizer
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        request.taskHint = .dictation

        let canOnDevice: Bool
        if #available(iOS 13.0, *) {
            canOnDevice = recognizer.supportsOnDeviceRecognition
            let useOnDevice = forceOnDevice ?? false
            request.requiresOnDeviceRecognition = useOnDevice && canOnDevice
        } else {
            canOnDevice = false
        }
        currentRequest = request

        let usingOnDevice: Bool
        if #available(iOS 13.0, *) { usingOnDevice = request.requiresOnDeviceRecognition }
        else { usingOnDevice = false }

        publishStatus(
            "Распознаю часть \(index + 1)/\(pieces.count)" +
            (usingOnDevice ? " · локально" : " · сервер") +
            (attempt > 0 ? " · повтор" : "")
        )

        var finished = false
        var latestText = bestPartial
        let pieceWatchdog = DispatchWorkItem { [weak self] in
            guard let self = self, self.activeItemID == item.id, !finished else { return }
            finished = true
            self.cleanupCurrentSpeechTask()
            self.workQueue.async {
                guard self.activeItemID == item.id else { return }
                if attempt == 0 {
                    self.publishStatus("Часть \(index + 1): timeout · один повтор")
                    self.recognizePiece(
                        item: item, sourceURL: sourceURL, pieces: pieces, index: index,
                        texts: texts, warnings: warnings, attempt: 1,
                        bestPartial: latestText, forceOnDevice: canOnDevice ? true : false
                    )
                } else {
                    let partial = self.mergeTranscriptPieces(texts + (latestText.isEmpty ? [] : [latestText]))
                    self.markNeedsPC(item: item, sourceURL: sourceURL, reason: "Speech timeout на части \(index + 1)/\(pieces.count)", partialText: partial)
                }
            }
        }
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 30, execute: pieceWatchdog)

        currentTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
            guard let self = self, self.activeItemID == item.id, !finished else { return }
            if let result = result {
                let value = result.bestTranscription.formattedString.trimmingCharacters(in: .whitespacesAndNewlines)
                if !value.isEmpty { latestText = value }
                if result.isFinal {
                    finished = true
                    pieceWatchdog.cancel()
                    let accepted = latestText
                    self.cleanupCurrentSpeechTask()
                    self.workQueue.async {
                        guard self.activeItemID == item.id else { return }
                        self.recognizePieces(
                            item: item, sourceURL: sourceURL, pieces: pieces, index: index + 1,
                            texts: texts + (accepted.isEmpty ? [] : [accepted]), warnings: warnings
                        )
                    }
                    return
                }
            }

            guard let error = error else { return }
            finished = true
            pieceWatchdog.cancel()
            let chain = self.speechErrorChain(error)
            let diagnostic = self.fullSpeechError(error, piece: index + 1, total: pieces.count, attempt: attempt + 1)
            self.cleanupCurrentSpeechTask()
            self.workQueue.async {
                guard self.activeItemID == item.id else { return }
                let has = { (domain: String, code: Int) in chain.contains { $0.domain == domain && $0.code == code } }

                if has("kAFAssistantErrorDomain", 1110) {
                    self.recognizePieces(
                        item: item, sourceURL: sourceURL, pieces: pieces, index: index + 1,
                        texts: texts + (latestText.isEmpty ? [] : [latestText]), warnings: warnings
                    )
                    return
                }

                let retryable =
                    has("kAFAssistantErrorDomain", 203) || has("SiriSpeechErrorDomain", 1) ||
                    has("SiriSpeechErrorDomain", 101) || has("SiriSpeechErrorDomain", 102) ||
                    has("kAFAssistantErrorDomain", 33) || has("kAFAssistantErrorDomain", 1100) ||
                    has("kAFAssistantErrorDomain", 1101) || has("kAFAssistantErrorDomain", 1107) ||
                    has("kLSRErrorDomain", 102) || has("kLSRErrorDomain", 300)

                if retryable && attempt == 0 {
                    self.publishStatus("Часть \(index + 1): ошибка · один повтор")
                    self.recognizePiece(
                        item: item, sourceURL: sourceURL, pieces: pieces, index: index,
                        texts: texts, warnings: warnings, attempt: 1,
                        bestPartial: latestText, forceOnDevice: canOnDevice ? true : false
                    )
                    return
                }

                let partial = self.mergeTranscriptPieces(texts + (latestText.isEmpty ? [] : [latestText]))
                self.markNeedsPC(item: item, sourceURL: sourceURL, reason: diagnostic, partialText: partial)
            }
        }

        do {
            let audioFile = try AVAudioFile(forReading: pieces[index])
            let format = audioFile.processingFormat
            let capacity: AVAudioFrameCount = 4096
            while audioFile.framePosition < audioFile.length {
                guard activeItemID == item.id, !finished else { break }
                guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: capacity) else {
                    throw NSError(domain: "WearMemoryText.Speech", code: 5, userInfo: [NSLocalizedDescriptionKey: "Не удалось создать PCM-буфер"])
                }
                try audioFile.read(into: buffer, frameCount: capacity)
                if buffer.frameLength == 0 { break }
                request.append(buffer)
            }
            if !finished { request.endAudio() }
        } catch {
            pieceWatchdog.cancel()
            finished = true
            cleanupCurrentSpeechTask()
            markNeedsPC(item: item, sourceURL: sourceURL, reason: "Чтение аудио для Speech: \(error.localizedDescription)", partialText: mergeTranscriptPieces(texts))
        }
    }

'''
s=s[:start]+newfunc+s[end:]

needle='''    ) {\n        guard index < pieces.count else {\n            let text = mergeTranscriptPieces(texts)\n\n            if text.isEmpty && !warnings.isEmpty {\n                finishFailure(itemID: item.id, message: warnings.joined(separator: " | "))\n            } else {\n                finishSuccess(item: item, sourceURL: sourceURL, text: text, warnings: warnings)\n            }\n            return\n        }\n'''
repl='''    ) {\n        guard activeItemID == item.id else { return }\n        guard index < pieces.count else {\n            let text = mergeTranscriptPieces(texts)\n            if warnings.isEmpty {\n                finishSuccess(item: item, sourceURL: sourceURL, text: text, warnings: [])\n            } else {\n                markNeedsPC(item: item, sourceURL: sourceURL, reason: warnings.joined(separator: " | "), partialText: text)\n            }\n            return\n        }\n'''
if needle not in s: raise SystemExit('recognizePieces end block not found')
s=s.replace(needle,repl,1)

ins='''    private func finishSuccess(item: TextQueueItem, sourceURL: URL, text: String, warnings: [String] = []) {\n'''
helpers=r'''    private func startFileDeadline(item: TextQueueItem, sourceURL: URL) {
        fileDeadlineWorkItem?.cancel()
        let work = DispatchWorkItem { [weak self] in
            guard let self = self, self.activeItemID == item.id else { return }
            self.cleanupCurrentSpeechTask()
            self.workQueue.async {
                guard self.activeItemID == item.id else { return }
                self.markNeedsPC(item: item, sourceURL: sourceURL, reason: "Общий лимит обработки на iPod: 3 минуты", partialText: "")
            }
        }
        fileDeadlineWorkItem = work
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + maxFileProcessingSeconds, execute: work)
    }

    private func stopFileDeadline() {
        fileDeadlineWorkItem?.cancel()
        fileDeadlineWorkItem = nil
    }

    private func updateSpeechSidecar(for sourceURL: URL, status: String, reason: String? = nil, partialText: String? = nil) throws -> URL {
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

    private func markNeedsPC(item: TextQueueItem, sourceURL: URL, reason: String, partialText: String) {
        guard activeItemID == item.id else { return }
        stopFileDeadline()
        cleanupCurrentSpeechTask()
        do {
            let metadata = try metadataForAudio(sourceURL)
            if !partialText.isEmpty {
                let draft = TranscriptResult(
                    sourceFileName: item.sourceFileName, startedAt: metadata.startedAt, endedAt: metadata.endedAt,
                    processedAt: Date(), language: language.rawValue, text: partialText, warnings: [reason]
                )
                try encoder.encode(draft).write(to: resultURL(for: item.id), options: .atomic)
            }
            let metaURL = try updateSpeechSidecar(for: sourceURL, status: "needs_pc", reason: reason, partialText: partialText)
            var queue = loadQueue(); queue.removeAll { $0.id == item.id }; saveQueue(queue)
            activeItemID = nil
            setProcessingLocked(false)
            DispatchQueue.main.async {
                self.lastError = reason
                self.statusText = "needs_pc · передано на компьютер"
                self.onStateChanged?()
                self.onNeedsPC?(sourceURL, metaURL)
            }
            try? fm.removeItem(at: speechTempDirectory)
            processNextLocked()
        } catch {
            activeItemID = nil
            setProcessingLocked(false)
            publishError("needs_pc: \(error.localizedDescription)")
            processNextLocked()
        }
    }

'''
if ins not in s: raise SystemExit('finishSuccess marker not found')
s=s.replace(ins,helpers+ins,1)

old='''            try encoder.encode(result).write(to: resultURL(for: item.id), options: .atomic)\n            let journal = try rebuildDailyJournal(for: metadata.startedAt)\n\n            var queue = loadQueue(); queue.removeAll { $0.id == item.id }; saveQueue(queue)\n            setProcessingLocked(false)\n'''
new='''            try encoder.encode(result).write(to: resultURL(for: item.id), options: .atomic)\n            _ = try updateSpeechSidecar(for: sourceURL, status: "recognized_complete")\n            let journal = try rebuildDailyJournal(for: metadata.startedAt)\n\n            var queue = loadQueue(); queue.removeAll { $0.id == item.id }; saveQueue(queue)\n            stopFileDeadline()\n            activeItemID = nil\n            setProcessingLocked(false)\n'''
if old not in s: raise SystemExit('finish success body not found')
s=s.replace(old,new,1)

old='''                    case .failure(let error): self.finishFailure(itemID: item.id, message: "Подготовка аудио: \\(error.localizedDescription)")\n'''
new='''                    case .failure(let error): self.markNeedsPC(item: item, sourceURL: sourceURL, reason: "Подготовка аудио: \\(error.localizedDescription)", partialText: "")\n'''
if old not in s: raise SystemExit('split failure not found')
s=s.replace(old,new,1)
proc.write_text(s)

m=model.read_text()
old='''        processor.onJournalUpdated = { [weak self] url in\n            self?.drive.enqueueText(url)\n            DispatchQueue.main.async { self?.refreshJournals() }\n        }\n'''
new='''        processor.onJournalUpdated = { [weak self] url in\n            self?.drive.enqueueText(url)\n            DispatchQueue.main.async { self?.refreshJournals() }\n        }\n        processor.onNeedsPC = { [weak self] audioURL, metadataURL in\n            self?.drive.enqueueAudioForPC(audioURL, metadataURL: metadataURL)\n        }\n'''
if old not in m: raise SystemExit('model callback not found')
m=m.replace(old,new,1)
model.write_text(m)

d=drive.read_text()
d=d.replace('''    static let textFolderID = "12ACQobm9LRdmmgPixarKN_trU55GiwXs"\n''','''    static let textFolderID = "12ACQobm9LRdmmgPixarKN_trU55GiwXs"\n    static let audioFolderID = "1DxRqc1GP6TeSmRM0IhORnXzksZopWIj2"\n''',1)
d=d.replace('''    private struct PendingItem: Codable, Equatable {\n        let id: String\n        let path: String\n    }\n''','''    private struct PendingItem: Codable, Equatable {\n        let id: String\n        let path: String\n        let folderID: String?\n        let mimeType: String?\n    }\n''',1)
d=d.replace('''            queue.append(PendingItem(id: "text:\\(sourceURL.lastPathComponent):\\(UUID().uuidString)", path: sourceURL.path))\n''','''            queue.append(PendingItem(id: "text:\\(sourceURL.lastPathComponent):\\(UUID().uuidString)", path: sourceURL.path, folderID: Self.textFolderID, mimeType: "text/plain; charset=utf-8"))\n''',1)
marker='''    func flushQueue() {\n        workQueue.async { self.flushQueueLocked() }\n    }\n'''
audio=r'''    func enqueueAudioForPC(_ audioURL: URL, metadataURL: URL) {
        workQueue.async {
            guard self.fm.fileExists(atPath: audioURL.path), self.fm.fileExists(atPath: metadataURL.path) else {
                self.setError("needs_pc: M4A или metadata не найдены")
                return
            }
            var queue = self.loadQueue()
            let urls: [(URL, String)] = [(audioURL, "audio/mp4"), (metadataURL, "application/json; charset=utf-8")]
            for (url, mime) in urls {
                queue.removeAll { URL(fileURLWithPath: $0.path).lastPathComponent == url.lastPathComponent }
                queue.append(PendingItem(
                    id: "pc:\(url.lastPathComponent):\(UUID().uuidString)",
                    path: url.path,
                    folderID: Self.audioFolderID,
                    mimeType: mime
                ))
            }
            self.saveQueue(queue)
            self.flushQueueLocked()
        }
    }

'''
if marker not in d: raise SystemExit('flush marker not found')
d=d.replace(marker,audio+marker,1)
d=d.replace('''        let mappingKey = "text.drive.remote.\\(sourceURL.lastPathComponent)"\n''','''        let folderID = item.folderID ?? Self.textFolderID\n        let mimeType = item.mimeType ?? "text/plain; charset=utf-8"\n        let mappingKey = "text.drive.remote.\\(folderID).\\(sourceURL.lastPathComponent)"\n''',1)
d=d.replace('''            req.setValue("text/plain; charset=utf-8", forHTTPHeaderField: "Content-Type")\n''','''            req.setValue(mimeType, forHTTPHeaderField: "Content-Type")\n''',1)
d=d.replace('''                parentID: Self.textFolderID,\n                accessToken: accessToken,\n                itemID: item.id\n''','''                parentID: folderID,\n                mimeType: mimeType,\n                accessToken: accessToken,\n                itemID: item.id\n''',1)
d=d.replace('''    private func makeMultipartRequest(name: String, data: Data, parentID: String, accessToken: String, itemID: String) throws -> (request: URLRequest, bodyURL: URL) {\n''','''    private func makeMultipartRequest(name: String, data: Data, parentID: String, mimeType: String, accessToken: String, itemID: String) throws -> (request: URLRequest, bodyURL: URL) {\n''',1)
d=d.replace('''        body.append("\\r\\n--\\(boundary)\\r\\nContent-Type: text/plain; charset=utf-8\\r\\n\\r\\n".data(using: .utf8)!)\n''','''        body.append("\\r\\n--\\(boundary)\\r\\nContent-Type: \\(mimeType)\\r\\n\\r\\n".data(using: .utf8)!)\n''',1)
drive.write_text(d)

print('patched')
