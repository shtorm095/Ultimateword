from pathlib import Path

root = Path('/tmp/wmtext121-src')
app = root / 'WearMemoryText'
header = app / 'WMWhisperProductionBridge.h'
bridge = app / 'WMWhisperProductionBridge.mm'
recognizer = app / 'WhisperLocalRecognizer.swift'

for path in (header, bridge, recognizer):
    if not path.exists():
        raise SystemExit(f'missing {path}')

# Native bridge: expose Whisper segment start/end times and text.
h = header.read_text()
old = '''const char * _Nullable wm_prod_whisper_transcribe(const char * _Nonnull modelPath,
                                                   const float * _Nonnull samples,
                                                   int sampleCount,
                                                   double * _Nullable elapsedSeconds,
                                                   char * _Nullable * _Nullable tokenDetailsOut,
                                                   char * _Nullable * _Nullable errorOut);'''
new = '''const char * _Nullable wm_prod_whisper_transcribe(const char * _Nonnull modelPath,
                                                   const float * _Nonnull samples,
                                                   int sampleCount,
                                                   double * _Nullable elapsedSeconds,
                                                   char * _Nullable * _Nullable tokenDetailsOut,
                                                   char * _Nullable * _Nullable segmentDetailsOut,
                                                   char * _Nullable * _Nullable errorOut);'''
if old not in h:
    raise SystemExit('bridge header signature not found')
h = h.replace(old, new, 1)
header.write_text(h)

b = bridge.read_text()
old = '''const char *wm_prod_whisper_transcribe(const char *modelPath,
                                       const float *samples,
                                       int sampleCount,
                                       double *elapsedSeconds,
                                       char **tokenDetailsOut,
                                       char **errorOut) {
    if (tokenDetailsOut) *tokenDetailsOut = nullptr;
    if (errorOut) *errorOut = nullptr;'''
new = '''const char *wm_prod_whisper_transcribe(const char *modelPath,
                                       const float *samples,
                                       int sampleCount,
                                       double *elapsedSeconds,
                                       char **tokenDetailsOut,
                                       char **segmentDetailsOut,
                                       char **errorOut) {
    if (tokenDetailsOut) *tokenDetailsOut = nullptr;
    if (segmentDetailsOut) *segmentDetailsOut = nullptr;
    if (errorOut) *errorOut = nullptr;'''
if old not in b:
    raise SystemExit('bridge implementation signature not found')
b = b.replace(old, new, 1)

if '    params.single_segment = true;\n' not in b:
    raise SystemExit('single_segment setting not found')
b = b.replace('    params.single_segment = true;\n', '    params.single_segment = false;\n', 1)
if '    params.no_timestamps = true;\n' not in b:
    raise SystemExit('no_timestamps setting not found')
b = b.replace('    params.no_timestamps = true;\n', '    params.no_timestamps = false;\n', 1)

old = '''    std::string result;
    std::string tokenDetails;
    const int count = whisper_full_n_segments(ctx);
    for (int i = 0; i < count; ++i) {
        const char *text = whisper_full_get_segment_text(ctx, i);
        if (text) result += text;

        const int tokenCount = whisper_full_n_tokens(ctx, i);'''
new = '''    std::string result;
    std::string tokenDetails;
    std::string segmentDetails;
    const int count = whisper_full_n_segments(ctx);
    for (int i = 0; i < count; ++i) {
        const char *text = whisper_full_get_segment_text(ctx, i);
        if (text) {
            result += text;
            // whisper segment times are centiseconds; convert to milliseconds.
            segmentDetails += std::to_string(whisper_full_get_segment_t0(ctx, i) * 10);
            segmentDetails += "\\t";
            segmentDetails += std::to_string(whisper_full_get_segment_t1(ctx, i) * 10);
            segmentDetails += "\\t";
            segmentDetails += wm_prod_escape_token(text);
            segmentDetails += "\\n";
        }

        const int tokenCount = whisper_full_n_tokens(ctx, i);'''
if old not in b:
    raise SystemExit('result loop start not found')
b = b.replace(old, new, 1)

old = '''    if (tokenDetailsOut) *tokenDetailsOut = wm_prod_copy_string(tokenDetails);
    whisper_free(ctx);'''
new = '''    if (tokenDetailsOut) *tokenDetailsOut = wm_prod_copy_string(tokenDetails);
    if (segmentDetailsOut) *segmentDetailsOut = wm_prod_copy_string(segmentDetails);
    whisper_free(ctx);'''
if old not in b:
    raise SystemExit('bridge output block not found')
b = b.replace(old, new, 1)
bridge.write_text(b)

# Conservative local speaker clustering. It is additive: if two speaker clusters
# are not clearly separated, the transcript is left unlabelled instead of inventing speakers.
(app / 'SpeakerDiarizer.swift').write_text(r'''import Foundation

struct WhisperTimedSegment {
    let text: String
    let startSample: Int
    let endSample: Int
}

enum SpeakerDiarizer {
    private struct VoiceFeature {
        let zcr: Double
        let roughness: Double
        let pitchHz: Double
        let harmonicity: Double
    }

    static func formatIfReliable(
        segments: [WhisperTimedSegment],
        samples: [Float],
        sampleRate: Double
    ) -> String? {
        let usable = segments.filter {
            !$0.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
            $0.endSample > $0.startSample &&
            Double($0.endSample - $0.startSample) / sampleRate >= 0.45
        }
        guard usable.count >= 4 else { return nil }

        var features: [VoiceFeature] = []
        var keptSegments: [WhisperTimedSegment] = []
        for segment in usable {
            if let feature = feature(for: segment, samples: samples, sampleRate: sampleRate) {
                features.append(feature)
                keptSegments.append(segment)
            }
        }
        guard features.count >= 4 else { return nil }

        let vectors = normalizedVectors(features)
        guard let rawLabels = clusterTwo(vectors) else { return nil }

        let count0 = rawLabels.filter { $0 == 0 }.count
        let count1 = rawLabels.count - count0
        guard count0 >= 2, count1 >= 2 else { return nil }

        let c0 = centroid(vectors: vectors, labels: rawLabels, target: 0)
        let c1 = centroid(vectors: vectors, labels: rawLabels, target: 1)
        let between = distance(c0, c1)
        let within = averageWithinDistance(vectors: vectors, labels: rawLabels, c0: c0, c1: c1)

        // Avoid inventing speakers when one voice merely changes volume/prosody.
        guard between >= 1.35, between >= within * 1.55 else { return nil }

        // Speaker 1 is the person who appears first in time, for stable labels.
        let firstCluster = rawLabels[0]
        let mapped = rawLabels.map { $0 == firstCluster ? 1 : 2 }

        var lines: [String] = []
        var currentSpeaker: Int?
        var currentText = ""

        for (index, segment) in keptSegments.enumerated() {
            let speaker = mapped[index]
            let text = segment.text.trimmingCharacters(in: .whitespacesAndNewlines)
            if text.isEmpty { continue }

            if currentSpeaker == speaker {
                currentText = appendWithoutImmediateDuplicate(currentText, text)
            } else {
                if let existing = currentSpeaker, !currentText.isEmpty {
                    lines.append("[Sprecher \(existing)] \(currentText)")
                }
                currentSpeaker = speaker
                currentText = text
            }
        }
        if let existing = currentSpeaker, !currentText.isEmpty {
            lines.append("[Sprecher \(existing)] \(currentText)")
        }

        return lines.count >= 2 ? lines.joined(separator: "\n") : nil
    }

    private static func feature(
        for segment: WhisperTimedSegment,
        samples: [Float],
        sampleRate: Double
    ) -> VoiceFeature? {
        let lower = max(0, min(samples.count, segment.startSample))
        let upper = max(lower, min(samples.count, segment.endSample))
        guard upper - lower >= Int(sampleRate * 0.35) else { return nil }

        let frame = max(80, Int(sampleRate * 0.025))
        let hop = max(40, Int(sampleRate * 0.010))
        var energies: [(Int, Double)] = []
        var pos = lower
        while pos + frame <= upper {
            var sum = 0.0
            for i in pos..<(pos + frame) {
                let value = Double(samples[i])
                sum += value * value
            }
            energies.append((pos, sqrt(sum / Double(frame))))
            pos += hop
        }
        guard let strongest = energies.max(by: { $0.1 < $1.1 }), strongest.1 > 0.0015 else { return nil }

        let analysisLength = min(Int(sampleRate * 0.8), upper - lower)
        var start = strongest.0 - analysisLength / 2
        start = max(lower, min(start, upper - analysisLength))
        let end = start + analysisLength
        guard end > start + 100 else { return nil }

        var sumSq = 0.0
        var diff = 0.0
        var crossings = 0
        var previous = Double(samples[start])
        for i in (start + 1)..<end {
            let value = Double(samples[i])
            sumSq += value * value
            diff += abs(value - previous)
            if (value >= 0) != (previous >= 0) { crossings += 1 }
            previous = value
        }
        let n = Double(end - start)
        let rms = sqrt(max(1e-12, sumSq / n))
        let zcr = Double(crossings) / n
        let roughness = (diff / n) / max(1e-6, rms)
        let (pitch, harmonicity) = estimatePitch(samples: samples, start: start, end: end, sampleRate: sampleRate)

        return VoiceFeature(zcr: zcr, roughness: roughness, pitchHz: pitch, harmonicity: harmonicity)
    }

    private static func estimatePitch(
        samples: [Float],
        start: Int,
        end: Int,
        sampleRate: Double
    ) -> (Double, Double) {
        // Downsample to reduce A10 CPU cost. Search 65...350 Hz.
        let strideValue = 4
        var x: [Double] = []
        x.reserveCapacity((end - start) / strideValue + 1)
        var i = start
        while i < end {
            x.append(Double(samples[i]))
            i += strideValue
        }
        guard x.count > 200 else { return (0, 0) }

        let mean = x.reduce(0, +) / Double(x.count)
        for index in x.indices { x[index] -= mean }
        let rate = sampleRate / Double(strideValue)
        let minLag = max(2, Int(rate / 350.0))
        let maxLag = min(x.count / 3, Int(rate / 65.0))
        guard maxLag > minLag else { return (0, 0) }

        var bestLag = 0
        var bestCorrelation = 0.0
        for lag in minLag...maxLag {
            var cross = 0.0
            var e0 = 0.0
            var e1 = 0.0
            let limit = x.count - lag
            var j = 0
            while j < limit {
                let a = x[j]
                let b = x[j + lag]
                cross += a * b
                e0 += a * a
                e1 += b * b
                j += 1
            }
            let denom = sqrt(max(1e-12, e0 * e1))
            let correlation = cross / denom
            if correlation > bestCorrelation {
                bestCorrelation = correlation
                bestLag = lag
            }
        }
        guard bestLag > 0, bestCorrelation >= 0.18 else { return (0, max(0, bestCorrelation)) }
        return (rate / Double(bestLag), bestCorrelation)
    }

    private static func normalizedVectors(_ features: [VoiceFeature]) -> [[Double]] {
        let raw = features.map { feature -> [Double] in
            let pitch = feature.pitchHz > 0 ? log(feature.pitchHz) : log(120.0)
            return [feature.zcr, feature.roughness, pitch, feature.harmonicity]
        }
        let dimensions = 4
        var means = [Double](repeating: 0, count: dimensions)
        var scales = [Double](repeating: 1, count: dimensions)
        for d in 0..<dimensions {
            means[d] = raw.map { $0[d] }.reduce(0, +) / Double(raw.count)
            let variance = raw.map { value in
                let delta = value[d] - means[d]
                return delta * delta
            }.reduce(0, +) / Double(raw.count)
            scales[d] = max(1e-6, sqrt(variance))
        }
        return raw.map { value in
            (0..<dimensions).map { d in (value[d] - means[d]) / scales[d] }
        }
    }

    private static func clusterTwo(_ vectors: [[Double]]) -> [Int]? {
        guard vectors.count >= 4 else { return nil }
        var seedA = 0
        var seedB = 1
        var farthest = -1.0
        for i in 0..<vectors.count {
            for j in (i + 1)..<vectors.count {
                let d = distance(vectors[i], vectors[j])
                if d > farthest {
                    farthest = d
                    seedA = i
                    seedB = j
                }
            }
        }
        guard farthest >= 1.0 else { return nil }

        var c0 = vectors[seedA]
        var c1 = vectors[seedB]
        var labels = [Int](repeating: 0, count: vectors.count)
        for _ in 0..<12 {
            var changed = false
            for index in vectors.indices {
                let next = distance(vectors[index], c0) <= distance(vectors[index], c1) ? 0 : 1
                if labels[index] != next { labels[index] = next; changed = true }
            }
            let n0 = labels.filter { $0 == 0 }.count
            let n1 = labels.count - n0
            guard n0 > 0, n1 > 0 else { return nil }
            c0 = centroid(vectors: vectors, labels: labels, target: 0)
            c1 = centroid(vectors: vectors, labels: labels, target: 1)
            if !changed { break }
        }
        return labels
    }

    private static func centroid(vectors: [[Double]], labels: [Int], target: Int) -> [Double] {
        var result = [Double](repeating: 0, count: vectors[0].count)
        var count = 0.0
        for (index, vector) in vectors.enumerated() where labels[index] == target {
            for d in result.indices { result[d] += vector[d] }
            count += 1
        }
        if count > 0 {
            for d in result.indices { result[d] /= count }
        }
        return result
    }

    private static func averageWithinDistance(
        vectors: [[Double]], labels: [Int], c0: [Double], c1: [Double]
    ) -> Double {
        guard !vectors.isEmpty else { return 0 }
        var total = 0.0
        for index in vectors.indices {
            total += distance(vectors[index], labels[index] == 0 ? c0 : c1)
        }
        return total / Double(vectors.count)
    }

    private static func distance(_ a: [Double], _ b: [Double]) -> Double {
        sqrt(zip(a, b).map { pair in
            let delta = pair.0 - pair.1
            return delta * delta
        }.reduce(0, +))
    }

    private static func appendWithoutImmediateDuplicate(_ left: String, _ right: String) -> String {
        let leftWords = left.split(whereSeparator: { $0.isWhitespace }).map(String.init)
        let rightWords = right.split(whereSeparator: { $0.isWhitespace }).map(String.init)
        let maximum = min(16, min(leftWords.count, rightWords.count))
        var overlap = 0
        if maximum >= 3 {
            for size in stride(from: maximum, through: 3, by: -1) {
                let l = leftWords.suffix(size).map(normalizedWord)
                let r = rightWords.prefix(size).map(normalizedWord)
                if l == r { overlap = size; break }
            }
        }
        let remainder = rightWords.dropFirst(overlap).joined(separator: " ")
        if remainder.isEmpty { return left }
        return left.isEmpty ? remainder : left + " " + remainder
    }

    private static func normalizedWord(_ value: String) -> String {
        value.lowercased().trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
    }
}
''')

r = recognizer.read_text()
old = '''        var parts: [String] = []
        var confidences: [WhisperTokenConfidence] = []
'''
new = '''        var parts: [String] = []
        var confidences: [WhisperTokenConfidence] = []
        var timedSegments: [WhisperTimedSegment] = []
'''
if old not in r:
    raise SystemExit('recognizer collections block not found')
r = r.replace(old, new, 1)

old = '''            var elapsed: Double = 0
            var tokenDetailsPointer: UnsafeMutablePointer<CChar>?
            var errorPointer: UnsafeMutablePointer<CChar>?
'''
new = '''            var elapsed: Double = 0
            var tokenDetailsPointer: UnsafeMutablePointer<CChar>?
            var segmentDetailsPointer: UnsafeMutablePointer<CChar>?
            var errorPointer: UnsafeMutablePointer<CChar>?
'''
if old not in r:
    raise SystemExit('pointer declarations not found')
r = r.replace(old, new, 1)

old = '''                        &elapsed,
                        &tokenDetailsPointer,
                        &errorPointer
'''
new = '''                        &elapsed,
                        &tokenDetailsPointer,
                        &segmentDetailsPointer,
                        &errorPointer
'''
if old not in r:
    raise SystemExit('bridge call arguments not found')
r = r.replace(old, new, 1)

old = '''                wm_prod_whisper_free_string(errorPointer)
                if let tokenDetailsPointer { wm_prod_whisper_free_string(tokenDetailsPointer) }
                throw WhisperLocalRecognizerError.whisper("Teil \\(chunkIndex + 1)/\\(totalChunks): \\(message)")
'''
new = '''                wm_prod_whisper_free_string(errorPointer)
                if let tokenDetailsPointer { wm_prod_whisper_free_string(tokenDetailsPointer) }
                if let segmentDetailsPointer { wm_prod_whisper_free_string(segmentDetailsPointer) }
                throw WhisperLocalRecognizerError.whisper("Teil \\(chunkIndex + 1)/\\(totalChunks): \\(message)")
'''
if old not in r:
    raise SystemExit('error cleanup block not found')
r = r.replace(old, new, 1)

old = '''            guard let resultPointer else {
                if let tokenDetailsPointer { wm_prod_whisper_free_string(tokenDetailsPointer) }
                throw WhisperLocalRecognizerError.whisper("Teil \\(chunkIndex + 1)/\\(totalChunks): kein Ergebnis")
            }
'''
new = '''            guard let resultPointer else {
                if let tokenDetailsPointer { wm_prod_whisper_free_string(tokenDetailsPointer) }
                if let segmentDetailsPointer { wm_prod_whisper_free_string(segmentDetailsPointer) }
                throw WhisperLocalRecognizerError.whisper("Teil \\(chunkIndex + 1)/\\(totalChunks): kein Ergebnis")
            }
'''
if old not in r:
    raise SystemExit('nil result cleanup block not found')
r = r.replace(old, new, 1)

old = '''            if let tokenDetailsPointer {
                let details = String(cString: tokenDetailsPointer)
                wm_prod_whisper_free_string(tokenDetailsPointer)
                confidences.append(contentsOf: parseTokenDetails(details))
            }

            progress?(chunkIndex + 1, totalChunks)
'''
new = '''            if let tokenDetailsPointer {
                let details = String(cString: tokenDetailsPointer)
                wm_prod_whisper_free_string(tokenDetailsPointer)
                confidences.append(contentsOf: parseTokenDetails(details))
            }

            if let segmentDetailsPointer {
                let details = String(cString: segmentDetailsPointer)
                wm_prod_whisper_free_string(segmentDetailsPointer)
                timedSegments.append(contentsOf: parseSegmentDetails(details, chunkOffset: lower))
            }

            progress?(chunkIndex + 1, totalChunks)
'''
if old not in r:
    raise SystemExit('details parsing block not found')
r = r.replace(old, new, 1)

old = '''        let merged = mergeChunkTexts(parts)
        return GermanTranscriptPostProcessor.process(merged, tokens: confidences)
    }

    private static func parseTokenDetails'''
new = '''        let plainMerged = mergeChunkTexts(parts)
        let transcript = SpeakerDiarizer.formatIfReliable(
            segments: timedSegments,
            samples: samples,
            sampleRate: targetRate
        ) ?? plainMerged
        return GermanTranscriptPostProcessor.process(transcript, tokens: confidences)
    }

    private static func parseSegmentDetails(_ details: String, chunkOffset: Int) -> [WhisperTimedSegment] {
        var output: [WhisperTimedSegment] = []
        for line in details.split(separator: "\\n", omittingEmptySubsequences: true) {
            let columns = line.split(separator: "\\t", maxSplits: 2, omittingEmptySubsequences: false)
            guard columns.count == 3,
                  let startMs = Int(columns[0]),
                  let endMs = Int(columns[1]),
                  endMs > startMs else { continue }
            var text = String(columns[2])
            text = text.replacingOccurrences(of: "\\\\n", with: "\\n")
            text = text.replacingOccurrences(of: "\\\\t", with: "\\t")
            text = text.replacingOccurrences(of: "\\\\r", with: "\\r")
            text = text.replacingOccurrences(of: "\\\\\\\\", with: "\\\\")
            let startSample = chunkOffset + Int((Double(startMs) / 1000.0) * targetRate)
            let endSample = chunkOffset + Int((Double(endMs) / 1000.0) * targetRate)
            output.append(WhisperTimedSegment(text: text, startSample: startSample, endSample: endSample))
        }
        return output
    }

    private static func parseTokenDetails'''
if old not in r:
    raise SystemExit('recognizer final merge block not found')
r = r.replace(old, new, 1)
recognizer.write_text(r)

assert 'params.single_segment = false;' in bridge.read_text()
assert 'params.no_timestamps = false;' in bridge.read_text()
assert 'whisper_full_get_segment_t0(ctx, i) * 10' in bridge.read_text()
assert 'segmentDetailsOut' in header.read_text()
assert 'SpeakerDiarizer.formatIfReliable' in recognizer.read_text()
assert (app / 'SpeakerDiarizer.swift').exists()
print('speaker layer added: Whisper segment timing + conservative local two-speaker clustering')
