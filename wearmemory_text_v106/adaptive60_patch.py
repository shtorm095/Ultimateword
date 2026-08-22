from pathlib import Path

p = Path('WearMemoryText/TextProcessor.swift')
s = p.read_text()

old = '''        var ranges: [(Double, Double)] = []
        var start = 0.0
        while start < seconds {
            // Keep slices short on iOS 15; prerecorded-file recognition has an
            // undocumented failure mode around the old 15-second boundary.
            let duration = min(8.0, seconds - start)
            ranges.append((start, duration)); start += duration
        }
        exportPiece(asset: asset, sourceURL: sourceURL, ranges: ranges, index: 0, output: [], completion: completion)
'''
new = '''        // Primary recognition uses 60-second windows to preserve linguistic context.
        // Adjacent windows overlap by 5 seconds so words crossing a boundary are not lost.
        // A failed long window is adaptively split to ~30-second windows below.
        var ranges: [(Double, Double)] = []
        var start = 0.0
        let primaryDuration = 60.0
        let primaryOverlap = 5.0
        let primaryStep = primaryDuration - primaryOverlap
        while start < seconds {
            let duration = min(primaryDuration, seconds - start)
            ranges.append((start, duration))
            if start + duration >= seconds { break }
            start += primaryStep
        }
        exportPiece(asset: asset, sourceURL: sourceURL, ranges: ranges, index: 0, output: [], completion: completion)
'''
if old not in s:
    raise SystemExit('initial segmentation block not found')
s = s.replace(old, new)

old = '''            let text = texts
                .filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
                .joined(separator: " ")
                .trimmingCharacters(in: .whitespacesAndNewlines)
'''
new = '''            let text = mergeTranscriptPieces(texts)
'''
if old not in s:
    raise SystemExit('join block not found')
s = s.replace(old, new)

needle = '''                let retryable =
                    has("kAFAssistantErrorDomain", 203) ||
                    has("SiriSpeechErrorDomain", 1) ||
                    has("kAFAssistantErrorDomain", 33) ||
                    has("kAFAssistantErrorDomain", 1100) ||
                    has("kAFAssistantErrorDomain", 1101) ||
                    has("kAFAssistantErrorDomain", 1107) ||
                    has("kLSRErrorDomain", 102) ||
                    has("kLSRErrorDomain", 300)

                if retryable && attempt < 3 {
'''
replacement = '''                let retryable =
                    has("kAFAssistantErrorDomain", 203) ||
                    has("SiriSpeechErrorDomain", 1) ||
                    has("kAFAssistantErrorDomain", 33) ||
                    has("kAFAssistantErrorDomain", 1100) ||
                    has("kAFAssistantErrorDomain", 1101) ||
                    has("kAFAssistantErrorDomain", 1107) ||
                    has("kLSRErrorDomain", 102) ||
                    has("kLSRErrorDomain", 300)

                // Do not force the whole recording into tiny chunks. If a primary
                // ~60-second window fails, only that window is subdivided into
                // ~30-second windows with 3-second overlap and retried.
                if retryable && attempt == 0 && self.audioDuration(pieces[index]) > 35.0 {
                    self.publishStatus("Часть \\(index + 1): делю 60 с → 30 с после ошибки")
                    self.splitFailedPiece(pieces[index]) { splitResult in
                        self.workQueue.async {
                            switch splitResult {
                            case .success(let subpieces):
                                var expanded = pieces
                                expanded.remove(at: index)
                                expanded.insert(contentsOf: subpieces, at: index)
                                self.recognizePieces(
                                    item: item,
                                    sourceURL: sourceURL,
                                    pieces: expanded,
                                    index: index,
                                    texts: texts,
                                    warnings: warnings + [diagnostic]
                                )
                            case .failure:
                                self.recognizePiece(
                                    item: item,
                                    sourceURL: sourceURL,
                                    pieces: pieces,
                                    index: index,
                                    texts: texts,
                                    warnings: warnings,
                                    attempt: attempt + 1,
                                    bestPartial: latestText,
                                    forceOnDevice: usingOnDevice ? false : (canOnDevice ? true : false)
                                )
                            }
                        }
                    }
                    return
                }

                if retryable && attempt < 3 {
'''
if needle not in s:
    raise SystemExit('retry block not found')
s = s.replace(needle, replacement)

insert_before = '''    private func speechErrorChain(_ error: Error) -> [NSError] {
'''
helpers = '''    private func audioDuration(_ url: URL) -> Double {
        let value = CMTimeGetSeconds(AVURLAsset(url: url).duration)
        return value.isFinite ? max(0, value) : 0
    }

    private func splitFailedPiece(_ pieceURL: URL, completion: @escaping (Result<[URL], Error>) -> Void) {
        let asset = AVURLAsset(url: pieceURL)
        let seconds = CMTimeGetSeconds(asset.duration)
        guard seconds.isFinite, seconds > 0 else {
            completion(.failure(NSError(domain: "WearMemoryText.Speech", code: 6, userInfo: [NSLocalizedDescriptionKey: "Неверная длительность проблемной части"])))
            return
        }
        var ranges: [(Double, Double)] = []
        var start = 0.0
        let duration = 30.0
        let overlap = 3.0
        let step = duration - overlap
        while start < seconds {
            let length = min(duration, seconds - start)
            ranges.append((start, length))
            if start + length >= seconds { break }
            start += step
        }
        exportAdaptiveSubpiece(asset: asset, sourceURL: pieceURL, ranges: ranges, index: 0, output: [], completion: completion)
    }

    private func exportAdaptiveSubpiece(asset: AVAsset, sourceURL: URL, ranges: [(Double, Double)], index: Int, output: [URL], completion: @escaping (Result<[URL], Error>) -> Void) {
        guard index < ranges.count else { completion(.success(output)); return }
        guard let exporter = AVAssetExportSession(asset: asset, presetName: AVAssetExportPresetAppleM4A) else {
            completion(.failure(NSError(domain: "WearMemoryText.Speech", code: 7, userInfo: [NSLocalizedDescriptionKey: "Не удалось создать 30-секундный фрагмент"])))
            return
        }
        let stem = sourceURL.deletingPathExtension().lastPathComponent
        let out = speechTempDirectory.appendingPathComponent("\\(stem)-fallback-\\(String(format: "%02d", index)).m4a")
        try? fm.removeItem(at: out)
        exporter.outputURL = out
        exporter.outputFileType = .m4a
        let r = ranges[index]
        exporter.timeRange = CMTimeRange(start: CMTime(seconds: r.0, preferredTimescale: 600), duration: CMTime(seconds: r.1, preferredTimescale: 600))
        exporter.exportAsynchronously { [weak self] in
            guard let self = self else { return }
            if exporter.status == .completed {
                self.exportAdaptiveSubpiece(asset: asset, sourceURL: sourceURL, ranges: ranges, index: index + 1, output: output + [out], completion: completion)
            } else {
                completion(.failure(exporter.error ?? NSError(domain: "WearMemoryText.Speech", code: 8, userInfo: [NSLocalizedDescriptionKey: "Экспорт 30-секундного фрагмента не завершён"])))
            }
        }
    }

    private func mergeTranscriptPieces(_ texts: [String]) -> String {
        let cleaned = texts.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
        guard var merged = cleaned.first else { return "" }
        for next in cleaned.dropFirst() {
            let left = merged.split(separator: " ").map(String.init)
            let right = next.split(separator: " ").map(String.init)
            let maxCheck = min(24, min(left.count, right.count))
            var overlapWords = 0
            if maxCheck > 0 {
                for count in stride(from: maxCheck, through: 1, by: -1) {
                    let suffix = left.suffix(count).map { $0.folding(options: [.diacriticInsensitive, .caseInsensitive], locale: .current) }
                    let prefix = right.prefix(count).map { $0.folding(options: [.diacriticInsensitive, .caseInsensitive], locale: .current) }
                    if suffix == prefix { overlapWords = count; break }
                }
            }
            let addition = right.dropFirst(overlapWords).joined(separator: " ")
            if !addition.isEmpty { merged += " " + addition }
        }
        return merged.trimmingCharacters(in: .whitespacesAndNewlines)
    }

'''
if insert_before not in s:
    raise SystemExit('helper insertion point not found')
s = s.replace(insert_before, helpers + insert_before)

p.write_text(s)
