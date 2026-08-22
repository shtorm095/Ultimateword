import Foundation
import Speech
import AVFoundation

final class TextProcessor: ObservableObject {
    @Published private(set) var speechAuthorization: SFSpeechRecognizerAuthorizationStatus = SFSpeechRecognizer.authorizationStatus()
    @Published private(set) var pendingCount = 0
    @Published private(set) var statusText = "Ожидание"
    @Published private(set) var lastError: String?
    @Published private(set) var lastResult: TranscriptResult?
    @Published private(set) var isProcessing = false

    var language: TextLanguage = .german
    var onJournalUpdated: ((URL) -> Void)?
    var onStateChanged: (() -> Void)?

    private let fm = FileManager.default
    private let workQueue = DispatchQueue(label: "WearMemoryText.Processor", qos: .utility)
    private var currentTask: SFSpeechRecognitionTask?
    private var currentRecognizer: SFSpeechRecognizer?
    private var currentRequest: SFSpeechRecognitionRequest?
    private var retryWorkItem: DispatchWorkItem?
    // Internal serialization flag. The UI-facing @Published property is updated
    // asynchronously on main and must not be used as the lock for the 4 s poller.
    private var processingLocked = false

    private let encoder: JSONEncoder = {
        let e = JSONEncoder(); e.dateEncodingStrategy = .iso8601; e.outputFormatting = [.prettyPrinted, .sortedKeys]; return e
    }()
    private let decoder: JSONDecoder = {
        let d = JSONDecoder(); d.dateDecodingStrategy = .iso8601; return d
    }()

    deinit { currentTask?.cancel(); currentTask = nil; currentRecognizer = nil; currentRequest = nil; retryWorkItem?.cancel() }

    func requestAuthorization(completion: (() -> Void)? = nil) {
        SFSpeechRecognizer.requestAuthorization { [weak self] status in
            DispatchQueue.main.async {
                self?.speechAuthorization = status
                if status == .authorized { self?.statusText = "Speech разрешён" }
                completion?()
            }
        }
    }

    func refreshQueue(autoProcess: Bool = true) {
        workQueue.async { [weak self] in
            guard let self = self else { return }
            do {
                try self.ensureDirectories()
                var queue = self.loadQueue()
                let results = Set(try self.resultFiles().map { $0.deletingPathExtension().lastPathComponent })
                let inbox = try SharedTextPaths(fileManager: self.fm).audioInbox
                let files = try self.fm.contentsOfDirectory(at: inbox, includingPropertiesForKeys: [.fileSizeKey], options: [.skipsHiddenFiles])
                    .filter { $0.pathExtension.lowercased() == "m4a" }
                    .sorted { $0.lastPathComponent < $1.lastPathComponent }

                for url in files {
                    let key = url.deletingPathExtension().lastPathComponent
                    let size = (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
                    guard size > 0, !results.contains(key), !queue.contains(where: { $0.sourceFileName == url.lastPathComponent }) else { continue }
                    queue.append(TextQueueItem(
                        id: key,
                        sourceFileName: url.lastPathComponent,
                        state: .queued,
                        attempts: 0,
                        lastError: nil,
                        nextRetryAt: nil,
                        discoveredAt: Date()
                    ))
                }
                queue.removeAll { item in
                    let url = inbox.appendingPathComponent(item.sourceFileName)
                    return !self.fm.fileExists(atPath: url.path) && !results.contains(item.id)
                }
                self.saveQueue(queue)
                self.publishPending(queue.count)
                if autoProcess { self.processNextLocked() }
            } catch {
                self.publishError("Очередь: \(error.localizedDescription)")
            }
        }
    }

    func processAll() {
        workQueue.async { [weak self] in
            guard let self = self else { return }
            var queue = self.loadQueue()
            for index in queue.indices where queue[index].state == .retry || queue[index].state == .failed {
                queue[index].nextRetryAt = nil
                queue[index].state = .queued
                queue[index].lastError = nil
            }
            self.saveQueue(queue)
            self.processNextLocked()
        }
    }

    private func processNextLocked() {
        guard !processingLocked else { return }
        guard speechAuthorization == .authorized else {
            publishStatus("Нужно разрешение Speech")
            return
        }
        var queue = loadQueue()
        guard !queue.isEmpty else {
            publishStatus("Очередь пуста")
            return
        }

        let now = Date()
        guard let index = queue.firstIndex(where: { item in
            if item.state == .queued { return true }
            if item.state == .retry { return item.nextRetryAt.map { $0 <= now } ?? true }
            return false
        }) else {
            scheduleNextRetry(queue)
            return
        }

        let item = queue[index]
        do {
            let paths = try SharedTextPaths(fileManager: fm)
            let sourceURL = paths.audioInbox.appendingPathComponent(item.sourceFileName)
            guard fm.fileExists(atPath: sourceURL.path) else {
                queue.remove(at: index); saveQueue(queue); processNextLocked(); return
            }
            queue[index].state = .processing
            queue[index].lastError = nil
            saveQueue(queue)
            setProcessingLocked(true)
            publishStatus("Распознаю \(item.sourceFileName)")
            splitIntoPieces(sourceURL) { [weak self] result in
                guard let self = self else { return }
                self.workQueue.async {
                    switch result {
                    case .failure(let error): self.finishFailure(itemID: item.id, message: "Подготовка аудио: \(error.localizedDescription)")
                    case .success(let pieces): self.recognizePieces(item: item, sourceURL: sourceURL, pieces: pieces, index: 0, texts: [])
                    }
                }
            }
        } catch {
            finishFailure(itemID: item.id, message: error.localizedDescription)
        }
    }

    private func splitIntoPieces(_ sourceURL: URL, completion: @escaping (Result<[URL], Error>) -> Void) {
        let asset = AVURLAsset(url: sourceURL)
        let seconds = CMTimeGetSeconds(asset.duration)
        guard seconds.isFinite, seconds > 0 else {
            completion(.failure(NSError(domain: "WearMemoryText.Speech", code: 2, userInfo: [NSLocalizedDescriptionKey: "Неверная длительность аудио"]))); return
        }
        do { try ensureDirectories(); try? fm.removeItem(at: speechTempDirectory); try fm.createDirectory(at: speechTempDirectory, withIntermediateDirectories: true) }
        catch { completion(.failure(error)); return }

        var ranges: [(Double, Double)] = []
        var start = 0.0
        while start < seconds {
            // Keep slices short on iOS 15; prerecorded-file recognition has an
            // undocumented failure mode around the old 15-second boundary.
            let duration = min(8.0, seconds - start)
            ranges.append((start, duration)); start += duration
        }
        exportPiece(asset: asset, sourceURL: sourceURL, ranges: ranges, index: 0, output: [], completion: completion)
    }

    private func exportPiece(asset: AVAsset, sourceURL: URL, ranges: [(Double, Double)], index: Int, output: [URL], completion: @escaping (Result<[URL], Error>) -> Void) {
        guard index < ranges.count else { completion(.success(output)); return }
        guard let exporter = AVAssetExportSession(asset: asset, presetName: AVAssetExportPresetAppleM4A) else {
            completion(.failure(NSError(domain: "WearMemoryText.Speech", code: 3, userInfo: [NSLocalizedDescriptionKey: "Не удалось создать экспорт аудио"]))); return
        }
        let out = speechTempDirectory.appendingPathComponent("\(sourceURL.deletingPathExtension().lastPathComponent)-\(String(format: "%03d", index)).m4a")
        try? fm.removeItem(at: out)
        exporter.outputURL = out
        exporter.outputFileType = .m4a
        let range = ranges[index]
        exporter.timeRange = CMTimeRange(start: CMTime(seconds: range.0, preferredTimescale: 600), duration: CMTime(seconds: range.1, preferredTimescale: 600))
        exporter.exportAsynchronously { [weak self] in
            guard let self = self else { return }
            if exporter.status == .completed {
                self.exportPiece(asset: asset, sourceURL: sourceURL, ranges: ranges, index: index + 1, output: output + [out], completion: completion)
            } else {
                completion(.failure(exporter.error ?? NSError(domain: "WearMemoryText.Speech", code: 4, userInfo: [NSLocalizedDescriptionKey: "Экспорт части аудио не завершён"])))
            }
        }
    }

    private func recognizePieces(
        item: TextQueueItem,
        sourceURL: URL,
        pieces: [URL],
        index: Int,
        texts: [String],
        warnings: [String] = []
    ) {
        guard index < pieces.count else {
            let text = texts
                .filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
                .joined(separator: " ")
                .trimmingCharacters(in: .whitespacesAndNewlines)

            if text.isEmpty && !warnings.isEmpty {
                finishFailure(itemID: item.id, message: warnings.joined(separator: " | "))
            } else {
                finishSuccess(item: item, sourceURL: sourceURL, text: text, warnings: warnings)
            }
            return
        }

        recognizePiece(
            item: item,
            sourceURL: sourceURL,
            pieces: pieces,
            index: index,
            texts: texts,
            warnings: warnings,
            attempt: 0,
            bestPartial: ""
        )
    }

    private func recognizePiece(
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
        guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: language.rawValue)) else {
            finishFailure(itemID: item.id, message: "Язык \(language.rawValue) недоступен")
            return
        }
        guard recognizer.isAvailable else {
            finishFailure(itemID: item.id, message: "Apple Speech сейчас недоступен")
            return
        }

        // iOS 15 is prone to kAFAssistantErrorDomain 203 / SiriSpeechErrorDomain 1
        // when prerecorded audio is submitted through SFSpeechURLRecognitionRequest.
        // Feed the same file as PCM buffers instead. This uses the live-audio request
        // path without opening the microphone and avoids the URL-request timeout path.
        cleanupCurrentSpeechTask()
        currentRecognizer = recognizer

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        request.taskHint = .dictation

        let canOnDevice: Bool
        if #available(iOS 13.0, *) {
            canOnDevice = recognizer.supportsOnDeviceRecognition
            let useOnDevice = forceOnDevice ?? canOnDevice
            request.requiresOnDeviceRecognition = useOnDevice && canOnDevice
        } else {
            canOnDevice = false
        }
        currentRequest = request

        let usingOnDevice: Bool
        if #available(iOS 13.0, *) {
            usingOnDevice = request.requiresOnDeviceRecognition
        } else {
            usingOnDevice = false
        }

        publishStatus(
            "Распознаю часть \(index + 1)/\(pieces.count)" +
            (usingOnDevice ? " · локально" : " · сервер") +
            (attempt > 0 ? " · повтор" : "")
        )

        var finished = false
        var latestText = bestPartial

        currentTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
            guard let self = self, !finished else { return }

            if let result = result {
                let value = result.bestTranscription.formattedString
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                if !value.isEmpty { latestText = value }

                if result.isFinal {
                    finished = true
                    let accepted = latestText
                    self.cleanupCurrentSpeechTask()
                    self.workQueue.asyncAfter(deadline: .now() + 0.45) {
                        self.recognizePieces(
                            item: item,
                            sourceURL: sourceURL,
                            pieces: pieces,
                            index: index + 1,
                            texts: texts + (accepted.isEmpty ? [] : [accepted]),
                            warnings: warnings
                        )
                    }
                    return
                }
            }

            guard let error = error else { return }
            finished = true
            let chain = self.speechErrorChain(error)
            let diagnostic = self.fullSpeechError(error, piece: index + 1, total: pieces.count, attempt: attempt + 1)
            self.cleanupCurrentSpeechTask()

            self.workQueue.asyncAfter(deadline: .now() + 0.9) {
                let has = { (domain: String, code: Int) in
                    chain.contains { $0.domain == domain && $0.code == code }
                }

                if has("kAFAssistantErrorDomain", 1110) {
                    self.recognizePieces(
                        item: item,
                        sourceURL: sourceURL,
                        pieces: pieces,
                        index: index + 1,
                        texts: texts + (latestText.isEmpty ? [] : [latestText]),
                        warnings: warnings
                    )
                    return
                }

                if !latestText.isEmpty && (
                    has("kAFAssistantErrorDomain", 203) ||
                    has("SiriSpeechErrorDomain", 1) ||
                    has("kAFAssistantErrorDomain", 1101) ||
                    has("kAFAssistantErrorDomain", 1107)
                ) {
                    self.publishStatus("Часть \(index + 1): сохранён partial-результат")
                    self.recognizePieces(
                        item: item,
                        sourceURL: sourceURL,
                        pieces: pieces,
                        index: index + 1,
                        texts: texts + [latestText],
                        warnings: warnings + [diagnostic]
                    )
                    return
                }

                if has("kAFAssistantErrorDomain", 1700) {
                    self.finishFailure(itemID: item.id, message: "Speech не авторизован. Проверь разрешение Распознавание речи. " + diagnostic)
                    return
                }
                if has("kLSRErrorDomain", 201) {
                    self.finishFailure(itemID: item.id, message: "Siri/Диктовка отключена в iOS. Включи Диктовку и повтори. " + diagnostic)
                    return
                }

                let retryable =
                    has("kAFAssistantErrorDomain", 203) ||
                    has("SiriSpeechErrorDomain", 1) ||
                    has("kAFAssistantErrorDomain", 33) ||
                    has("kAFAssistantErrorDomain", 1100) ||
                    has("kAFAssistantErrorDomain", 1101) ||
                    has("kAFAssistantErrorDomain", 1107) ||
                    has("kLSRErrorDomain", 102) ||
                    has("kLSRErrorDomain", 300)

                if retryable && attempt < 3 {
                    let nextMode: Bool?
                    if usingOnDevice {
                        nextMode = false
                    } else if canOnDevice && attempt >= 1 {
                        nextMode = true
                    } else {
                        nextMode = false
                    }
                    self.publishStatus("Повтор части \(index + 1) · попытка \(attempt + 2)")
                    self.workQueue.asyncAfter(deadline: .now() + min(4.0, Double(attempt + 1) * 1.25)) {
                        self.recognizePiece(
                            item: item,
                            sourceURL: sourceURL,
                            pieces: pieces,
                            index: index,
                            texts: texts,
                            warnings: warnings,
                            attempt: attempt + 1,
                            bestPartial: latestText,
                            forceOnDevice: nextMode
                        )
                    }
                    return
                }

                self.publishStatus("Часть \(index + 1) пропущена после ошибок")
                self.recognizePieces(
                    item: item,
                    sourceURL: sourceURL,
                    pieces: pieces,
                    index: index + 1,
                    texts: texts,
                    warnings: warnings + [diagnostic]
                )
            }
        }

        do {
            let audioFile = try AVAudioFile(forReading: pieces[index])
            let format = audioFile.processingFormat
            let capacity: AVAudioFrameCount = 4096
            while audioFile.framePosition < audioFile.length {
                guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: capacity) else {
                    throw NSError(domain: "WearMemoryText.Speech", code: 5, userInfo: [NSLocalizedDescriptionKey: "Не удалось создать PCM-буфер"])
                }
                try audioFile.read(into: buffer, frameCount: capacity)
                if buffer.frameLength == 0 { break }
                request.append(buffer)
            }
            request.endAudio()
        } catch {
            finished = true
            cleanupCurrentSpeechTask()
            finishFailure(itemID: item.id, message: "Чтение аудио для Speech: \(error.localizedDescription)")
        }
    }

    private func speechErrorChain(_ error: Error) -> [NSError] {
        var output: [NSError] = []
        var current: NSError? = error as NSError
        var depth = 0
        while let ns = current, depth < 8 {
            output.append(ns)
            current = ns.userInfo[NSUnderlyingErrorKey] as? NSError
            depth += 1
        }
        return output
    }

    private func cleanupCurrentSpeechTask() {
        currentTask?.cancel()
        currentTask = nil
        currentRequest = nil
        currentRecognizer = nil
    }

    private func fullSpeechError(_ error: Error, piece: Int, total: Int, attempt: Int) -> String {
        var parts: [String] = []
        var current: NSError? = error as NSError
        var depth = 0
        while let ns = current, depth < 5 {
            var line = "часть \(piece)/\(total), попытка \(attempt): \(ns.domain) \(ns.code): \(ns.localizedDescription)"
            if let reason = ns.localizedFailureReason, !reason.isEmpty { line += "; reason=\(reason)" }
            if let suggestion = ns.localizedRecoverySuggestion, !suggestion.isEmpty { line += "; recovery=\(suggestion)" }
            parts.append(line)
            current = ns.userInfo[NSUnderlyingErrorKey] as? NSError
            depth += 1
        }
        return parts.joined(separator: " -> ")
    }

    private func finishSuccess(item: TextQueueItem, sourceURL: URL, text: String, warnings: [String] = []) {
        do {
            let metadata = try metadataForAudio(sourceURL)
            let result = TranscriptResult(
                sourceFileName: item.sourceFileName,
                startedAt: metadata.startedAt,
                endedAt: metadata.endedAt,
                processedAt: Date(),
                language: language.rawValue,
                text: text,
                warnings: warnings.isEmpty ? nil : warnings
            )
            try encoder.encode(result).write(to: resultURL(for: item.id), options: .atomic)
            let journal = try rebuildDailyJournal(for: metadata.startedAt)

            var queue = loadQueue(); queue.removeAll { $0.id == item.id }; saveQueue(queue)
            setProcessingLocked(false)
            DispatchQueue.main.async {
                self.lastResult = result
                self.lastError = warnings.isEmpty ? nil : warnings.joined(separator: " | ")
                if text.isEmpty {
                    self.statusText = "Готово · речь не найдена"
                } else if warnings.isEmpty {
                    self.statusText = "Готово"
                } else {
                    self.statusText = "Готово · с предупреждением"
                }
                self.onStateChanged?()
                self.onJournalUpdated?(journal)
            }
            try? fm.removeItem(at: speechTempDirectory)
            processNextLocked()
        } catch {
            finishFailure(itemID: item.id, message: "Сохранение текста: \(error.localizedDescription)")
        }
    }

    private func finishFailure(itemID: String, message: String) {
        var queue = loadQueue()
        if let index = queue.firstIndex(where: { $0.id == itemID }) {
            queue[index].attempts += 1
            queue[index].lastError = message
            if queue[index].attempts >= 3 {
                queue[index].state = .failed
                queue[index].nextRetryAt = nil
            } else {
                queue[index].state = .retry
                let delay = min(300.0, pow(2.0, Double(min(queue[index].attempts, 6))) * 5.0)
                queue[index].nextRetryAt = Date().addingTimeInterval(delay)
            }
        }
        saveQueue(queue)
        setProcessingLocked(false)
        publishError(message)
        try? fm.removeItem(at: speechTempDirectory)
        scheduleNextRetry(queue)
    }

    private func scheduleNextRetry(_ queue: [TextQueueItem]) {
        retryWorkItem?.cancel()
        let dates = queue.compactMap { $0.nextRetryAt }.filter { $0 > Date() }
        guard let next = dates.min() else { return }
        let delay = max(1.0, next.timeIntervalSinceNow)
        let item = DispatchWorkItem { [weak self] in self?.workQueue.async { self?.processNextLocked() } }
        retryWorkItem = item
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + delay, execute: item)
        publishStatus("Повтор через \(Int(delay.rounded())) с")
    }

    private func metadataForAudio(_ url: URL) throws -> AudioBridgeMetadata {
        let sidecar = url.deletingPathExtension().appendingPathExtension("meta.json")
        if fm.fileExists(atPath: sidecar.path) {
            return try decoder.decode(AudioBridgeMetadata.self, from: Data(contentsOf: sidecar))
        }
        let values = try url.resourceValues(forKeys: [.creationDateKey])
        let created = values.creationDate ?? Date()
        let asset = AVURLAsset(url: url)
        let duration = CMTimeGetSeconds(asset.duration)
        return AudioBridgeMetadata(bridgeVersion: nil, sourceFileName: url.lastPathComponent, startedAt: created, endedAt: created.addingTimeInterval(duration.isFinite ? max(0, duration) : 0), exportedAt: nil)
    }

    private func rebuildDailyJournal(for date: Date) throws -> URL {
        let day = dayKey(date)
        var results: [TranscriptResult] = []
        for url in try resultFiles() {
            if let result = try? decoder.decode(TranscriptResult.self, from: Data(contentsOf: url)), dayKey(result.startedAt) == day { results.append(result) }
        }
        results.sort { $0.startedAt < $1.startedAt }
        let timeFormatter = DateFormatter(); timeFormatter.locale = Locale(identifier: "en_US_POSIX"); timeFormatter.dateFormat = "HH:mm:ss"
        let content = results.map { "[\(timeFormatter.string(from: $0.startedAt))] \($0.text)" }.joined(separator: "\n") + (results.isEmpty ? "" : "\n")
        let url = journalsDirectory.appendingPathComponent("\(day).txt")
        try content.data(using: .utf8)?.write(to: url, options: .atomic)
        return url
    }

    private func dayKey(_ date: Date) -> String {
        let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "yyyy-MM-dd"; return f.string(from: date)
    }

    private func resultURL(for id: String) -> URL { resultsDirectory.appendingPathComponent("\(id).json") }
    private func resultFiles() throws -> [URL] {
        try ensureDirectories()
        return try fm.contentsOfDirectory(at: resultsDirectory, includingPropertiesForKeys: nil, options: [.skipsHiddenFiles]).filter { $0.pathExtension == "json" }
    }

    private var appSupport: URL { fm.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0] }
    var journalsDirectory: URL { fm.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("TextJournals", isDirectory: true) }
    private var resultsDirectory: URL { appSupport.appendingPathComponent("TranscriptResults", isDirectory: true) }
    private var queueURL: URL { appSupport.appendingPathComponent("TextQueue", isDirectory: true).appendingPathComponent("queue.json") }
    private var speechTempDirectory: URL { appSupport.appendingPathComponent("SpeechPieces", isDirectory: true) }

    private func ensureDirectories() throws {
        let paths = try SharedTextPaths(fileManager: fm); _ = paths
        try fm.createDirectory(at: resultsDirectory, withIntermediateDirectories: true)
        try fm.createDirectory(at: queueURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        try fm.createDirectory(at: journalsDirectory, withIntermediateDirectories: true)
        try fm.createDirectory(at: speechTempDirectory, withIntermediateDirectories: true)
    }

    private func loadQueue() -> [TextQueueItem] {
        guard let data = try? Data(contentsOf: queueURL), let q = try? decoder.decode([TextQueueItem].self, from: data) else { return [] }
        return q
    }
    private func saveQueue(_ queue: [TextQueueItem]) {
        try? ensureDirectories(); if let data = try? encoder.encode(queue) { try? data.write(to: queueURL, options: .atomic) }
        publishPending(queue.count)
    }
    private func publishPending(_ value: Int) { DispatchQueue.main.async { self.pendingCount = value; self.onStateChanged?() } }
    private func publishStatus(_ value: String) { DispatchQueue.main.async { self.statusText = value; self.onStateChanged?() } }
    private func publishError(_ value: String) { DispatchQueue.main.async { self.lastError = value; self.statusText = "Ошибка"; self.onStateChanged?() } }
    private func setProcessingLocked(_ value: Bool) {
        processingLocked = value
        DispatchQueue.main.async { self.isProcessing = value; self.onStateChanged?() }
    }
}
