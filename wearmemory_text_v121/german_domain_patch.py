from pathlib import Path
import re

root = Path('/tmp/wmtext121-src')
app = root / 'WearMemoryText'
header = app / 'WMWhisperProductionBridge.h'
bridge = app / 'WMWhisperProductionBridge.mm'
recognizer = app / 'WhisperLocalRecognizer.swift'
processor = app / 'TextProcessor.swift'

for path in (header, bridge, recognizer, processor):
    if not path.exists():
        raise SystemExit(f'missing {path}')

# --- Native Whisper bridge: expose token probabilities without changing the model. ---
h = header.read_text()
old_decl = '''const char * _Nullable wm_prod_whisper_transcribe(const char * _Nonnull modelPath,
                                                   const float * _Nonnull samples,
                                                   int sampleCount,
                                                   double * _Nullable elapsedSeconds,
                                                   char * _Nullable * _Nullable errorOut);'''
new_decl = '''const char * _Nullable wm_prod_whisper_transcribe(const char * _Nonnull modelPath,
                                                   const float * _Nonnull samples,
                                                   int sampleCount,
                                                   double * _Nullable elapsedSeconds,
                                                   char * _Nullable * _Nullable tokenDetailsOut,
                                                   char * _Nullable * _Nullable errorOut);'''
if old_decl not in h:
    raise SystemExit('Whisper bridge declaration not found')
h = h.replace(old_decl, new_decl, 1)
header.write_text(h)

b = bridge.read_text()
old_signature = '''const char *wm_prod_whisper_transcribe(const char *modelPath,
                                       const float *samples,
                                       int sampleCount,
                                       double *elapsedSeconds,
                                       char **errorOut) {
    if (errorOut) *errorOut = nullptr;'''
new_signature = '''const char *wm_prod_whisper_transcribe(const char *modelPath,
                                       const float *samples,
                                       int sampleCount,
                                       double *elapsedSeconds,
                                       char **tokenDetailsOut,
                                       char **errorOut) {
    if (tokenDetailsOut) *tokenDetailsOut = nullptr;
    if (errorOut) *errorOut = nullptr;'''
if old_signature not in b:
    raise SystemExit('Whisper bridge implementation signature not found')
b = b.replace(old_signature, new_signature, 1)

copy_helper_end = '''static char *wm_prod_copy_string(const std::string &value) {
    char *out = (char *)malloc(value.size() + 1);
    if (!out) return nullptr;
    memcpy(out, value.c_str(), value.size() + 1);
    return out;
}
'''
escape_helper = copy_helper_end + r'''
static std::string wm_prod_escape_token(const char *value) {
    std::string out;
    if (!value) return out;
    for (const char *p = value; *p; ++p) {
        switch (*p) {
            case '\\': out += "\\\\"; break;
            case '\t': out += "\\t"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            default: out += *p; break;
        }
    }
    return out;
}
'''
if copy_helper_end not in b:
    raise SystemExit('copy helper not found')
b = b.replace(copy_helper_end, escape_helper, 1)

needle = '    params.language = "de";\n'
if needle not in b:
    raise SystemExit('German language setting not found')
domain_prompt = needle + '''    params.initial_prompt = "Elektrotechnik, DIN VDE, VDE, Hager, Siemens, Brüstungskanal, Leitungsschutzschalter, FI-Schalter, RCD, Unterverteilung, Potentialausgleich, Baustromverteiler, Schaltschrank, Klemmen, Schütz, Sicherung, Steckdose, Leuchte, NOT-AUS, KNX, Siemens LOGO!, TN-C-S, PE, Neutralleiter, Außenleiter, Kabel, Leitung, Querschnitt.";\n'''
b = b.replace(needle, domain_prompt, 1)

old_result = '''    std::string result;
    const int count = whisper_full_n_segments(ctx);
    for (int i = 0; i < count; ++i) {
        const char *text = whisper_full_get_segment_text(ctx, i);
        if (text) result += text;
    }
    whisper_free(ctx);
'''
new_result = '''    std::string result;
    std::string tokenDetails;
    const int count = whisper_full_n_segments(ctx);
    for (int i = 0; i < count; ++i) {
        const char *text = whisper_full_get_segment_text(ctx, i);
        if (text) result += text;

        const int tokenCount = whisper_full_n_tokens(ctx, i);
        for (int j = 0; j < tokenCount; ++j) {
            const char *tokenText = whisper_full_get_token_text(ctx, i, j);
            if (!tokenText) continue;
            const float probability = whisper_full_get_token_p(ctx, i, j);
            tokenDetails += std::to_string(probability);
            tokenDetails += "\\t";
            tokenDetails += wm_prod_escape_token(tokenText);
            tokenDetails += "\\n";
        }
    }
    if (tokenDetailsOut) *tokenDetailsOut = wm_prod_copy_string(tokenDetails);
    whisper_free(ctx);
'''
if old_result not in b:
    raise SystemExit('Whisper result loop not found')
b = b.replace(old_result, new_result, 1)
bridge.write_text(b)

# --- German domain postprocessor. Conservative corrections only: known technical terms,
# whitespace/punctuation cleanup and repeated ASR boundary text. No semantic rewriting. ---
(app / 'GermanTranscriptPostProcessor.swift').write_text(r'''import Foundation

struct WhisperTokenConfidence {
    let text: String
    let probability: Double
}

struct WhisperRecognitionResult {
    let text: String
    let averageConfidence: Double
    let lowConfidenceTokens: [String]
    let corrections: Int
    let warnings: [String]
}

enum GermanTranscriptPostProcessor {
    private struct Rule {
        let pattern: String
        let replacement: String
    }

    // Deliberately narrow rules. They normalize vocabulary used in electrical/building work
    // without trying to rewrite arbitrary German sentences.
    private static let technicalRules: [Rule] = [
        Rule(pattern: #"(?i)\bD\s*I\s*N\s*[- ]*V\s*D\s*E\b"#, replacement: "DIN VDE"),
        Rule(pattern: #"(?i)\bV\s*D\s*E\b"#, replacement: "VDE"),
        Rule(pattern: #"(?i)\bhager\b"#, replacement: "Hager"),
        Rule(pattern: #"(?i)\bsiemens\b"#, replacement: "Siemens"),
        Rule(pattern: #"(?i)\bbr(?:ü|ue)stungs?\s*kanal\b"#, replacement: "Brüstungskanal"),
        Rule(pattern: #"(?i)\bleitungs?\s*schutz\s*schalter\b"#, replacement: "Leitungsschutzschalter"),
        Rule(pattern: #"(?i)\bleistungsschutzschalter\b"#, replacement: "Leitungsschutzschalter"),
        Rule(pattern: #"(?i)\bunter\s*verteilung\b"#, replacement: "Unterverteilung"),
        Rule(pattern: #"(?i)\bpotential\s*ausgleich\b"#, replacement: "Potentialausgleich"),
        Rule(pattern: #"(?i)\bbaustrom\s*verteiler\b"#, replacement: "Baustromverteiler"),
        Rule(pattern: #"(?i)\bfi\s*[- ]?\s*schalter\b"#, replacement: "FI-Schalter"),
        Rule(pattern: #"(?i)\bR\s*C\s*D\b"#, replacement: "RCD"),
        Rule(pattern: #"(?i)\bT\s*N\s*[- ]?\s*C\s*[- ]?\s*S\b"#, replacement: "TN-C-S"),
        Rule(pattern: #"(?i)\bnot\s*[- ]?\s*aus\b"#, replacement: "NOT-AUS"),
        Rule(pattern: #"(?i)\bsiemens\s+logo\s*!?\b"#, replacement: "Siemens LOGO!"),
        Rule(pattern: #"(?i)\bK\s*N\s*X\b"#, replacement: "KNX"),
        Rule(pattern: #"(?i)\b(\d+)\s*(?:mm2|mm\^2|quadratmillimeter)\b"#, replacement: "$1 mm²")
    ]

    static func process(_ raw: String, tokens: [WhisperTokenConfidence]) -> WhisperRecognitionResult {
        var text = raw.precomposedStringWithCanonicalMapping
        var correctionCount = 0

        // Conversational-ASR cleanup: repeated fillers, spacing and punctuation only.
        (text, correctionCount) = applying(#"(?i)(?:\b(?:ähm+|äh+)\b[ ,]*){2,}"#, replacement: "", to: text, count: correctionCount)
        (text, correctionCount) = applying(#"[ \t]+"#, replacement: " ", to: text, count: correctionCount)
        (text, correctionCount) = applying(#"\s+([,.;:!?])"#, replacement: "$1", to: text, count: correctionCount)
        (text, correctionCount) = applying(#"([,.;:!?])(?=[A-Za-zÄÖÜäöüß])"#, replacement: "$1 ", to: text, count: correctionCount)

        for rule in technicalRules {
            (text, correctionCount) = applying(rule.pattern, replacement: rule.replacement, to: text, count: correctionCount)
        }

        text = removeAdjacentDuplicateSentences(text)
            .trimmingCharacters(in: .whitespacesAndNewlines)

        let meaningful = tokens.filter { token in
            let cleaned = cleanToken(token.text)
            return !cleaned.isEmpty && !cleaned.hasPrefix("<|") && token.probability.isFinite
        }
        let average = meaningful.isEmpty ? 1.0 : meaningful.map(\.probability).reduce(0, +) / Double(meaningful.count)

        var seen = Set<String>()
        var low: [String] = []
        for token in meaningful where token.probability < 0.45 {
            let word = cleanToken(token.text)
            guard word.count > 1 else { continue }
            let key = word.lowercased()
            if seen.insert(key).inserted {
                low.append(word)
                if low.count == 8 { break }
            }
        }

        var warnings: [String] = []
        if average < 0.55 {
            warnings.append("Whisper: низкая средняя уверенность \(Int((average * 100).rounded()))%")
        }
        if !low.isEmpty {
            warnings.append("Проверить слова: " + low.joined(separator: ", "))
        }

        return WhisperRecognitionResult(
            text: text,
            averageConfidence: average,
            lowConfidenceTokens: low,
            corrections: correctionCount,
            warnings: warnings
        )
    }

    private static func applying(_ pattern: String, replacement: String, to input: String, count: Int) -> (String, Int) {
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return (input, count) }
        let range = NSRange(input.startIndex..<input.endIndex, in: input)
        let matches = regex.numberOfMatches(in: input, range: range)
        guard matches > 0 else { return (input, count) }
        let output = regex.stringByReplacingMatches(in: input, range: range, withTemplate: replacement)
        return (output, count + matches)
    }

    private static func cleanToken(_ input: String) -> String {
        input
            .replacingOccurrences(of: "\\n", with: " ")
            .replacingOccurrences(of: "\\t", with: " ")
            .trimmingCharacters(in: CharacterSet.whitespacesAndNewlines.union(.punctuationCharacters))
    }

    private static func removeAdjacentDuplicateSentences(_ input: String) -> String {
        let pattern = #"(?i)([^.!?]{12,}[.!?])\s+\1(?:\s+|$)"#
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return input }
        var output = input
        for _ in 0..<3 {
            let range = NSRange(output.startIndex..<output.endIndex, in: output)
            let next = regex.stringByReplacingMatches(in: output, range: range, withTemplate: "$1 ")
            if next == output { break }
            output = next
        }
        return output
    }
}
''')

# --- Swift recognizer: collect token confidence and merge chunks without duplicate overlap. ---
r = recognizer.read_text()
start = r.index('    static func transcribe(url: URL, progress: ((Int, Int) -> Void)? = nil) throws -> String {')
end = r.index('\n    private static func decodeTo16kMonoFloat', start)
new_transcribe = r'''    static func transcribe(url: URL, progress: ((Int, Int) -> Void)? = nil) throws -> WhisperRecognitionResult {
        let samples = try decodeTo16kMonoFloat(url)
        guard !samples.isEmpty else { throw WhisperLocalRecognizerError.audioConvert("0 Samples") }
        guard let model = Bundle.main.url(forResource: "ggml-base", withExtension: "bin") else {
            throw WhisperLocalRecognizerError.modelMissing
        }

        let chunkSampleCount = Int(targetRate * 30.0)
        let totalChunks = max(1, Int(ceil(Double(samples.count) / Double(chunkSampleCount))))
        var parts: [String] = []
        var confidences: [WhisperTokenConfidence] = []

        for chunkIndex in 0..<totalChunks {
            let lower = chunkIndex * chunkSampleCount
            let upper = min(samples.count, lower + chunkSampleCount)
            let count = upper - lower
            if count <= 0 { continue }

            var elapsed: Double = 0
            var tokenDetailsPointer: UnsafeMutablePointer<CChar>?
            var errorPointer: UnsafeMutablePointer<CChar>?
            let resultPointer: UnsafePointer<CChar>? = model.path.withCString { modelPath in
                samples.withUnsafeBufferPointer { buffer in
                    guard let base = buffer.baseAddress else { return nil }
                    return wm_prod_whisper_transcribe(
                        modelPath,
                        base.advanced(by: lower),
                        Int32(count),
                        &elapsed,
                        &tokenDetailsPointer,
                        &errorPointer
                    )
                }
            }

            if let errorPointer {
                let message = String(cString: errorPointer)
                wm_prod_whisper_free_string(errorPointer)
                if let tokenDetailsPointer { wm_prod_whisper_free_string(tokenDetailsPointer) }
                throw WhisperLocalRecognizerError.whisper("Teil \(chunkIndex + 1)/\(totalChunks): \(message)")
            }
            guard let resultPointer else {
                if let tokenDetailsPointer { wm_prod_whisper_free_string(tokenDetailsPointer) }
                throw WhisperLocalRecognizerError.whisper("Teil \(chunkIndex + 1)/\(totalChunks): kein Ergebnis")
            }

            let text = String(cString: resultPointer).trimmingCharacters(in: .whitespacesAndNewlines)
            wm_prod_whisper_free_string(resultPointer)
            if !text.isEmpty { parts.append(text) }

            if let tokenDetailsPointer {
                let details = String(cString: tokenDetailsPointer)
                wm_prod_whisper_free_string(tokenDetailsPointer)
                confidences.append(contentsOf: parseTokenDetails(details))
            }

            progress?(chunkIndex + 1, totalChunks)
        }

        let merged = mergeChunkTexts(parts)
        return GermanTranscriptPostProcessor.process(merged, tokens: confidences)
    }

    private static func parseTokenDetails(_ details: String) -> [WhisperTokenConfidence] {
        var output: [WhisperTokenConfidence] = []
        for line in details.split(separator: "\n", omittingEmptySubsequences: true) {
            let columns = line.split(separator: "\t", maxSplits: 1, omittingEmptySubsequences: false)
            guard columns.count == 2, let probability = Double(columns[0]) else { continue }
            var token = String(columns[1])
            token = token.replacingOccurrences(of: "\\n", with: "\n")
            token = token.replacingOccurrences(of: "\\t", with: "\t")
            token = token.replacingOccurrences(of: "\\r", with: "\r")
            token = token.replacingOccurrences(of: "\\\\", with: "\\")
            if token.hasPrefix("<|") { continue }
            output.append(WhisperTokenConfidence(text: token, probability: probability))
        }
        return output
    }

    private static func mergeChunkTexts(_ parts: [String]) -> String {
        guard var merged = parts.first?.trimmingCharacters(in: .whitespacesAndNewlines), !merged.isEmpty else {
            return ""
        }
        for part in parts.dropFirst() {
            let incoming = part.trimmingCharacters(in: .whitespacesAndNewlines)
            if incoming.isEmpty { continue }
            let leftWords = merged.split(whereSeparator: { $0.isWhitespace }).map(String.init)
            let rightWords = incoming.split(whereSeparator: { $0.isWhitespace }).map(String.init)
            let maximum = min(20, min(leftWords.count, rightWords.count))
            var overlap = 0
            if maximum >= 3 {
                for size in stride(from: maximum, through: 3, by: -1) {
                    let left = leftWords.suffix(size).map(normalizedWord)
                    let right = rightWords.prefix(size).map(normalizedWord)
                    if left == right {
                        overlap = size
                        break
                    }
                }
            }
            let remainder = rightWords.dropFirst(overlap).joined(separator: " ")
            if !remainder.isEmpty {
                merged += merged.hasSuffix(" ") ? remainder : " " + remainder
            }
        }
        return merged
    }

    private static func normalizedWord(_ word: String) -> String {
        word.lowercased().trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
    }
'''
r = r[:start] + new_transcribe + r[end:]
recognizer.write_text(r)

# Processor stores only the corrected final text; confidence warnings stay in existing metadata/status path.
p = processor.read_text()
old_processor = '''            let text = try WhisperLocalRecognizer.transcribe(url: sourceURL) { [weak self] done, total in
                self?.publishStatus("Whisper \\(done)/\\(total) · \\(item.sourceFileName)")
            }
            finishSuccess(item: item, sourceURL: sourceURL, text: text, warnings: [])'''
new_processor = '''            let result = try WhisperLocalRecognizer.transcribe(url: sourceURL) { [weak self] done, total in
                self?.publishStatus("Whisper \\(done)/\\(total) · \\(item.sourceFileName)")
            }
            finishSuccess(item: item, sourceURL: sourceURL, text: result.text, warnings: result.warnings)'''
if old_processor not in p:
    raise SystemExit('processor Whisper call not found')
p = p.replace(old_processor, new_processor, 1)
processor.write_text(p)

# Build-time invariants.
assert 'params.initial_prompt = "Elektrotechnik' in bridge.read_text()
assert 'whisper_full_get_token_p(ctx, i, j)' in bridge.read_text()
assert 'GermanTranscriptPostProcessor.process' in recognizer.read_text()
assert 'finishSuccess(item: item, sourceURL: sourceURL, text: result.text, warnings: result.warnings)' in processor.read_text()
print('German domain layer added: technical vocabulary + conservative correction + token confidence + chunk deduplication')
