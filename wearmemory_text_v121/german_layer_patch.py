from pathlib import Path
import subprocess

root = Path('/tmp/wmtext121-src')
app = root / 'WearMemoryText'
bridge_h = app / 'WMWhisperProductionBridge.h'
bridge_mm = app / 'WMWhisperProductionBridge.mm'
recognizer = app / 'WhisperLocalRecognizer.swift'
processor = app / 'TextProcessor.swift'
info = app / 'Info.plist'

for p in (bridge_h, bridge_mm, recognizer, processor, info):
    if not p.exists():
        raise SystemExit(f'missing {p}')

# Extend the native bridge so every Whisper token carries its real probability.
h = bridge_h.read_text()
old_h = '''const char * _Nullable wm_prod_whisper_transcribe(const char * _Nonnull modelPath,
                                                   const float * _Nonnull samples,
                                                   int sampleCount,
                                                   double * _Nullable elapsedSeconds,
                                                   char * _Nullable * _Nullable errorOut);'''
new_h = '''const char * _Nullable wm_prod_whisper_transcribe(const char * _Nonnull modelPath,
                                                   const float * _Nonnull samples,
                                                   int sampleCount,
                                                   double * _Nullable elapsedSeconds,
                                                   char * _Nullable * _Nullable tokenJsonOut,
                                                   char * _Nullable * _Nullable errorOut);'''
if old_h not in h:
    raise SystemExit('bridge header signature not found')
h = h.replace(old_h, new_h, 1)
bridge_h.write_text(h)

m = bridge_mm.read_text()
m = m.replace('#include <string>\n', '#include <string>\n#include <cstdio>\n', 1)
old_sig = '''const char *wm_prod_whisper_transcribe(const char *modelPath,
                                       const float *samples,
                                       int sampleCount,
                                       double *elapsedSeconds,
                                       char **errorOut) {
    if (errorOut) *errorOut = nullptr;'''
new_sig = '''const char *wm_prod_whisper_transcribe(const char *modelPath,
                                       const float *samples,
                                       int sampleCount,
                                       double *elapsedSeconds,
                                       char **tokenJsonOut,
                                       char **errorOut) {
    if (tokenJsonOut) *tokenJsonOut = nullptr;
    if (errorOut) *errorOut = nullptr;'''
if old_sig not in m:
    raise SystemExit('bridge implementation signature not found')
m = m.replace(old_sig, new_sig, 1)

needle = '''static char *wm_prod_copy_string(const std::string &value) {
    char *out = (char *)malloc(value.size() + 1);
    if (!out) return nullptr;
    memcpy(out, value.c_str(), value.size() + 1);
    return out;
}
'''
helper = needle + r'''
static std::string wm_prod_json_escape(const char *input) {
    std::string out;
    if (!input) return out;
    for (const unsigned char *p = (const unsigned char *)input; *p; ++p) {
        switch (*p) {
            case '\\': out += "\\\\"; break;
            case '"':  out += "\\\""; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (*p < 0x20) {
                    char buf[8];
                    snprintf(buf, sizeof(buf), "\\u%04x", (unsigned)*p);
                    out += buf;
                } else {
                    out.push_back((char)*p);
                }
        }
    }
    return out;
}
'''
if needle not in m:
    raise SystemExit('copy-string helper not found')
m = m.replace(needle, helper, 1)

old_result = '''    std::string result;
    const int count = whisper_full_n_segments(ctx);
    for (int i = 0; i < count; ++i) {
        const char *text = whisper_full_get_segment_text(ctx, i);
        if (text) result += text;
    }
    whisper_free(ctx);
'''
new_result = r'''    std::string result;
    std::string tokenJson = "[";
    bool firstToken = true;
    const int count = whisper_full_n_segments(ctx);
    for (int i = 0; i < count; ++i) {
        const char *text = whisper_full_get_segment_text(ctx, i);
        if (text) result += text;

        const int nTokens = whisper_full_n_tokens(ctx, i);
        for (int j = 0; j < nTokens; ++j) {
            const char *piece = whisper_full_get_token_text(ctx, i, j);
            if (!piece || (piece[0] == '<' && piece[1] == '|')) continue;
            const float probability = whisper_full_get_token_p(ctx, i, j);
            char pbuf[32];
            snprintf(pbuf, sizeof(pbuf), "%.6f", (double)probability);
            if (!firstToken) tokenJson += ",";
            firstToken = false;
            tokenJson += "{\"t\":\"";
            tokenJson += wm_prod_json_escape(piece);
            tokenJson += "\",\"p\":";
            tokenJson += pbuf;
            tokenJson += "}";
        }
    }
    tokenJson += "]";
    if (tokenJsonOut) *tokenJsonOut = wm_prod_copy_string(tokenJson);
    whisper_free(ctx);
'''
if old_result not in m:
    raise SystemExit('bridge result block not found')
m = m.replace(old_result, new_result, 1)
bridge_mm.write_text(m)

# German post-processing layer. It is deterministic and offline: no cloud/LLM call.
(app / 'GermanTranscriptPostProcessor.swift').write_text(r'''import Foundation

struct GermanTranscriptResult {
    let text: String
    let averageConfidence: Double
    let lowConfidenceWords: [String]
    let correctionCount: Int
}

enum GermanTranscriptPostProcessor {
    private struct WordScore {
        let word: String
        let probability: Double
    }

    private static let lowConfidenceThreshold = 0.55
    private static let ambiguousCorrectionThreshold = 0.68

    static func process(rawText: String, tokens: [WhisperTokenConfidence]) -> GermanTranscriptResult {
        let wordScores = aggregateWords(tokens)
        var confidenceByWord: [String: Double] = [:]
        for score in wordScores {
            let key = normalizedWord(score.word)
            guard !key.isEmpty else { continue }
            confidenceByWord[key] = min(confidenceByWord[key] ?? 1.0, score.probability)
        }

        var text = normalizeWhitespace(rawText)
        var corrections = 0

        let safeRules: [(String, String)] = [
            (#"\bv\s*d\s*e\b"#, "VDE"),
            (#"\bd\s*g\s*u\s*v\b"#, "DGUV"),
            (#"\bm\s*l\s*a\s*r\b"#, "MLAR"),
            (#"\br\s*c\s*d\b"#, "RCD"),
            (#"\bt\s*a\s*b\b"#, "TAB"),
            (#"\bdin\s+vde\b"#, "DIN VDE"),
            (#"\bvde\s*[- ]?\s*ar\s*[- ]?\s*n\s*4100\b"#, "VDE-AR-N 4100"),
            (#"\bhager\b"#, "Hager"),
            (#"\bsiemens\b"#, "Siemens"),
            (#"\bbrüstungs?\s*kanal\b"#, "Brüstungskanal"),
            (#"\bbruestungs?\s*kanal\b"#, "Brüstungskanal"),
            (#"\bleitungs?\s*schutz\s*schalter\b"#, "Leitungsschutzschalter"),
            (#"\bfehlerstrom\s*schutz\s*schalter\b"#, "Fehlerstromschutzschalter"),
            (#"\bunter\s*verteilung\b"#, "Unterverteilung"),
            (#"\bhaupt\s*verteilung\b"#, "Hauptverteilung"),
            (#"\bpoten(?:t|z)ial\s*ausgleich\b"#, "Potentialausgleich"),
            (#"\büberspannungs?\s*schutz\b"#, "Überspannungsschutz"),
            (#"\bzähler\s*schrank\b"#, "Zählerschrank"),
            (#"\bkabel\s*rinne\b"#, "Kabelrinne"),
            (#"\bkabel\s*trasse\b"#, "Kabeltrasse"),
            (#"\binstallations?\s*kanal\b"#, "Installationskanal"),
            (#"\babzweig\s*dose\b"#, "Abzweigdose"),
            (#"\bverteil\s*dose\b"#, "Verteilerdose"),
            (#"\bsteck\s*dose\b"#, "Steckdose"),
            (#"\bfrequenz\s*umrichter\b"#, "Frequenzumrichter"),
            (#"\bsoft\s*starter\b"#, "Softstarter"),
            (#"\bschutz\s*leiter\b"#, "Schutzleiter"),
            (#"\bneutral\s*leiter\b"#, "Neutralleiter"),
            (#"\baußen\s*leiter\b"#, "Außenleiter"),
            (#"\bstern\s*[- ]?\s*dreieck\b"#, "Stern-Dreieck"),
            (#"\bwärme\s*pumpe\b"#, "Wärmepumpe"),
            (#"\bphoto\s*voltaik\b"#, "Photovoltaik"),
            (#"\bfi\s*[- ]?\s*schalter\b"#, "FI-Schalter"),
            (#"\bdas\s+heisst\b"#, "das heißt"),
            (#"\bich\s+hab\b"#, "ich habe"),
            (#"\bwir\s+ham\b"#, "wir haben"),
            (#"\bn\s+bisschen\b"#, "ein bisschen")
        ]
        for rule in safeRules {
            let result = replace(rule.0, with: rule.1, in: text)
            text = result.text
            corrections += result.count
        }

        // These aliases are intentionally corrected only when Whisper itself was unsure.
        let ambiguousRules: [(String, String, String)] = [
            (#"\bhaga\b"#, "Hager", "haga"),
            (#"\bhäger\b"#, "Hager", "häger"),
            (#"\bsiemans\b"#, "Siemens", "siemans"),
            (#"\bsimmens\b"#, "Siemens", "simmens"),
            (#"\bbrüstungskanahl\b"#, "Brüstungskanal", "brüstungskanahl"),
            (#"\bvdeh\b"#, "VDE", "vdeh")
        ]
        for rule in ambiguousRules {
            if let p = confidenceByWord[rule.2], p < ambiguousCorrectionThreshold {
                let result = replace(rule.0, with: rule.1, in: text)
                text = result.text
                corrections += result.count
            }
        }

        // Remove filler sounds and accidental repeated function words, but do not rewrite content words.
        var result = replace(#"(?i)(?<!\p{L})(?:ähm+|äh+)(?!\p{L})[, ]*"#, with: "", in: text)
        text = result.text
        corrections += result.count
        result = replace(#"(?i)\b(und|der|die|das|ich|wir|ist|sind|also)\s+\1\b"#, with: "$1", in: text)
        text = result.text
        corrections += result.count

        text = normalizePunctuation(normalizeWhitespace(text))
        text = capitalizeFirst(text)
        if let last = text.last, !".!?;:".contains(last) { text.append(".") }

        let average: Double
        if wordScores.isEmpty {
            average = 0
        } else {
            average = wordScores.map { $0.probability }.reduce(0, +) / Double(wordScores.count)
        }
        let lows = wordScores
            .filter { $0.probability < lowConfidenceThreshold }
            .map { normalizedWord($0.word) }
            .filter { !$0.isEmpty }
        var seen = Set<String>()
        let uniqueLows = lows.filter { seen.insert($0).inserted }

        return GermanTranscriptResult(
            text: text.trimmingCharacters(in: .whitespacesAndNewlines),
            averageConfidence: average,
            lowConfidenceWords: uniqueLows,
            correctionCount: corrections
        )
    }

    private static func aggregateWords(_ tokens: [WhisperTokenConfidence]) -> [WordScore] {
        var output: [WordScore] = []
        var current = ""
        var probs: [Double] = []

        func flush() {
            let word = current.trimmingCharacters(in: .whitespacesAndNewlines)
            if !word.isEmpty, !probs.isEmpty {
                output.append(WordScore(word: word, probability: probs.min() ?? 0))
            }
            current = ""
            probs.removeAll(keepingCapacity: true)
        }

        for token in tokens {
            let piece = token.text
            if piece.hasPrefix("<|") { continue }
            if piece.first?.isWhitespace == true { flush() }
            let chunks = piece.split(whereSeparator: { $0.isWhitespace })
            if chunks.count > 1 {
                for (index, chunk) in chunks.enumerated() {
                    if index > 0 { flush() }
                    current += String(chunk)
                    probs.append(token.probability)
                }
            } else {
                current += piece.trimmingCharacters(in: .whitespacesAndNewlines)
                probs.append(token.probability)
            }
        }
        flush()
        return output
    }

    private static func normalizedWord(_ value: String) -> String {
        value.lowercased().trimmingCharacters(in: CharacterSet.punctuationCharacters.union(.symbols))
    }

    private static func replace(_ pattern: String, with replacement: String, in input: String) -> (text: String, count: Int) {
        guard let regex = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]) else {
            return (input, 0)
        }
        let range = NSRange(input.startIndex..<input.endIndex, in: input)
        let count = regex.numberOfMatches(in: input, options: [], range: range)
        if count == 0 { return (input, 0) }
        return (regex.stringByReplacingMatches(in: input, options: [], range: range, withTemplate: replacement), count)
    }

    private static func normalizeWhitespace(_ input: String) -> String {
        input.replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func normalizePunctuation(_ input: String) -> String {
        var value = input.replacingOccurrences(of: #"\s+([,.;:!?])"#, with: "$1", options: .regularExpression)
        value = value.replacingOccurrences(of: #"([,.;:!?])(?=\p{L}|\p{N})"#, with: "$1 ", options: .regularExpression)
        return value
    }

    private static func capitalizeFirst(_ input: String) -> String {
        guard let first = input.first else { return input }
        return String(first).uppercased() + input.dropFirst()
    }
}
''')

# Replace the chunk recognizer with one that collects token confidence and removes
# only exact chunk-boundary duplication before German post-processing.
recognizer.write_text(r'''import Foundation
import AudioToolbox

struct WhisperTokenConfidence: Decodable {
    let text: String
    let probability: Double

    private enum CodingKeys: String, CodingKey {
        case text = "t"
        case probability = "p"
    }
}

enum WhisperLocalRecognizerError: LocalizedError {
    case modelMissing
    case audioOpen(String)
    case audioConvert(String)
    case whisper(String)

    var errorDescription: String? {
        switch self {
        case .modelMissing: return "Whisper Base Modell fehlt."
        case .audioOpen(let value): return "M4A konnte nicht geöffnet werden: \(value)"
        case .audioConvert(let value): return "Audio-Konvertierung fehlgeschlagen: \(value)"
        case .whisper(let value): return value
        }
    }
}

enum WhisperLocalRecognizer {
    private static let targetRate: Double = 16_000

    static func transcribe(url: URL, progress: ((Int, Int) -> Void)? = nil) throws -> GermanTranscriptResult {
        let samples = try decodeTo16kMonoFloat(url)
        guard !samples.isEmpty else { throw WhisperLocalRecognizerError.audioConvert("0 Samples") }
        guard let model = Bundle.main.url(forResource: "ggml-base", withExtension: "bin") else {
            throw WhisperLocalRecognizerError.modelMissing
        }

        let chunkSampleCount = Int(targetRate * 30.0)
        let totalChunks = max(1, Int(ceil(Double(samples.count) / Double(chunkSampleCount))))
        var assembled = ""
        var allTokens: [WhisperTokenConfidence] = []

        for chunkIndex in 0..<totalChunks {
            let lower = chunkIndex * chunkSampleCount
            let upper = min(samples.count, lower + chunkSampleCount)
            let count = upper - lower
            if count <= 0 { continue }

            var elapsed: Double = 0
            var tokenPointer: UnsafeMutablePointer<CChar>?
            var errorPointer: UnsafeMutablePointer<CChar>?
            let resultPointer: UnsafePointer<CChar>? = model.path.withCString { modelPath in
                samples.withUnsafeBufferPointer { buffer in
                    guard let base = buffer.baseAddress else { return nil }
                    return wm_prod_whisper_transcribe(
                        modelPath,
                        base.advanced(by: lower),
                        Int32(count),
                        &elapsed,
                        &tokenPointer,
                        &errorPointer
                    )
                }
            }

            if let errorPointer {
                let message = String(cString: errorPointer)
                wm_prod_whisper_free_string(errorPointer)
                if let tokenPointer { wm_prod_whisper_free_string(tokenPointer) }
                throw WhisperLocalRecognizerError.whisper("Teil \(chunkIndex + 1)/\(totalChunks): \(message)")
            }
            guard let resultPointer else {
                if let tokenPointer { wm_prod_whisper_free_string(tokenPointer) }
                throw WhisperLocalRecognizerError.whisper("Teil \(chunkIndex + 1)/\(totalChunks): kein Ergebnis")
            }

            let chunkText = String(cString: resultPointer).trimmingCharacters(in: .whitespacesAndNewlines)
            wm_prod_whisper_free_string(resultPointer)

            if let tokenPointer {
                let json = String(cString: tokenPointer)
                wm_prod_whisper_free_string(tokenPointer)
                if let data = json.data(using: .utf8),
                   let decoded = try? JSONDecoder().decode([WhisperTokenConfidence].self, from: data) {
                    allTokens.append(contentsOf: decoded)
                }
            }

            if !chunkText.isEmpty {
                assembled = appendWithoutBoundaryDuplicate(existing: assembled, next: chunkText)
            }
            progress?(chunkIndex + 1, totalChunks)
        }

        return GermanTranscriptPostProcessor.process(rawText: assembled, tokens: allTokens)
    }

    private static func appendWithoutBoundaryDuplicate(existing: String, next: String) -> String {
        let left = existing.split(whereSeparator: { $0.isWhitespace }).map(String.init)
        let right = next.split(whereSeparator: { $0.isWhitespace }).map(String.init)
        guard !left.isEmpty else { return next }
        guard !right.isEmpty else { return existing }

        let maxOverlap = min(12, min(left.count, right.count))
        var overlap = 0
        if maxOverlap >= 2 {
            for size in stride(from: maxOverlap, through: 2, by: -1) {
                let a = left.suffix(size).map { normalizedBoundaryWord($0) }
                let b = right.prefix(size).map { normalizedBoundaryWord($0) }
                if a == b {
                    overlap = size
                    break
                }
            }
        }
        let remaining = right.dropFirst(overlap).joined(separator: " ")
        if remaining.isEmpty { return existing }
        return existing + " " + remaining
    }

    private static func normalizedBoundaryWord(_ value: String) -> String {
        value.lowercased().trimmingCharacters(in: CharacterSet.punctuationCharacters.union(.symbols))
    }

    private static func decodeTo16kMonoFloat(_ url: URL) throws -> [Float] {
        var fileRef: ExtAudioFileRef?
        var status = ExtAudioFileOpenURL(url as CFURL, &fileRef)
        guard status == noErr, let fileRef else {
            throw WhisperLocalRecognizerError.audioOpen(osStatusDescription(status))
        }
        defer { ExtAudioFileDispose(fileRef) }

        var clientFormat = AudioStreamBasicDescription(
            mSampleRate: targetRate,
            mFormatID: kAudioFormatLinearPCM,
            mFormatFlags: kAudioFormatFlagsNativeFloatPacked,
            mBytesPerPacket: 4,
            mFramesPerPacket: 1,
            mBytesPerFrame: 4,
            mChannelsPerFrame: 1,
            mBitsPerChannel: 32,
            mReserved: 0
        )
        status = withUnsafePointer(to: &clientFormat) { ptr in
            ExtAudioFileSetProperty(
                fileRef,
                kExtAudioFileProperty_ClientDataFormat,
                UInt32(MemoryLayout<AudioStreamBasicDescription>.size),
                ptr
            )
        }
        guard status == noErr else {
            throw WhisperLocalRecognizerError.audioConvert("ClientDataFormat: \(osStatusDescription(status))")
        }

        let chunkFrames: UInt32 = 16_000 * 2
        var chunk = [Float](repeating: 0, count: Int(chunkFrames))
        var samples: [Float] = []
        while true {
            var frames = chunkFrames
            status = chunk.withUnsafeMutableBytes { rawBuffer in
                var bufferList = AudioBufferList(
                    mNumberBuffers: 1,
                    mBuffers: AudioBuffer(
                        mNumberChannels: 1,
                        mDataByteSize: UInt32(rawBuffer.count),
                        mData: rawBuffer.baseAddress
                    )
                )
                return ExtAudioFileRead(fileRef, &frames, &bufferList)
            }
            guard status == noErr else {
                throw WhisperLocalRecognizerError.audioConvert("ExtAudioFileRead: \(osStatusDescription(status))")
            }
            if frames == 0 { break }
            samples.append(contentsOf: chunk.prefix(Int(frames)))
        }
        return samples
    }

    private static func osStatusDescription(_ status: OSStatus) -> String {
        if status == noErr { return "noErr" }
        let value = UInt32(bitPattern: status)
        let chars: [UInt8] = [
            UInt8((value >> 24) & 0xff), UInt8((value >> 16) & 0xff),
            UInt8((value >> 8) & 0xff), UInt8(value & 0xff)
        ]
        if chars.allSatisfy({ $0 >= 32 && $0 <= 126 }),
           let fourCC = String(bytes: chars, encoding: .ascii) {
            return "OSStatus \(status) ('\(fourCC)')"
        }
        return "OSStatus \(status)"
    }
}
''')

p = processor.read_text()
old_process = '''            publishStatus("Whisper · \\(item.sourceFileName)")
            let text = try WhisperLocalRecognizer.transcribe(url: sourceURL) { [weak self] done, total in
                self?.publishStatus("Whisper \\(done)/\\(total) · \\(item.sourceFileName)")
            }
            finishSuccess(item: item, sourceURL: sourceURL, text: text, warnings: [])'''
new_process = '''            publishStatus("Whisper · \\(item.sourceFileName)")
            let result = try WhisperLocalRecognizer.transcribe(url: sourceURL) { [weak self] done, total in
                self?.publishStatus("Whisper \\(done)/\\(total) · \\(item.sourceFileName)")
            }
            publishStatus("Deutsch korrigiert · \\(Int(result.averageConfidence * 100))%")
            finishSuccess(item: item, sourceURL: sourceURL, text: result.text, warnings: [])'''
if old_process not in p:
    raise SystemExit('chunk recognizer call not found')
p = p.replace(old_process, new_process, 1)
processor.write_text(p)

# Version bump distinguishes the post-processing build from the saving-only build.
subprocess.run(['/usr/libexec/PlistBuddy', '-c', 'Set :CFBundleShortVersionString 1.2.2', str(info)], check=True)
subprocess.run(['/usr/libexec/PlistBuddy', '-c', 'Set :CFBundleVersion 22', str(info)], check=True)

print('German technical layer enabled: confidence + conservative corrections + chunk dedup')
