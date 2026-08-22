from pathlib import Path
import re
import subprocess

root = Path('/tmp/wmtext121-src')
app = root / 'WearMemoryText'
bridge_h = app / 'WMWhisperProductionBridge.h'
bridge_mm = app / 'WMWhisperProductionBridge.mm'
recognizer = app / 'WhisperLocalRecognizer.swift'
processor = app / 'TextProcessor.swift'
content = app / 'ContentView.swift'
info = app / 'Info.plist'

for path in (bridge_h, bridge_mm, recognizer, processor, content, info):
    if not path.exists():
        raise SystemExit(f'missing {path}')

# Keep the verified average confidence API and add token text/probability details.
h = bridge_h.read_text()
old_decl = '''const char * _Nullable wm_prod_whisper_transcribe(const char * _Nonnull modelPath,
                                                   const float * _Nonnull samples,
                                                   int sampleCount,
                                                   double * _Nullable elapsedSeconds,
                                                   float * _Nullable confidenceOut,
                                                   int * _Nullable scoredTokenCountOut,
                                                   char * _Nullable * _Nullable errorOut);'''
new_decl = '''const char * _Nullable wm_prod_whisper_transcribe(const char * _Nonnull modelPath,
                                                   const float * _Nonnull samples,
                                                   int sampleCount,
                                                   double * _Nullable elapsedSeconds,
                                                   float * _Nullable confidenceOut,
                                                   int * _Nullable scoredTokenCountOut,
                                                   char * _Nullable * _Nullable tokenDetailsOut,
                                                   char * _Nullable * _Nullable errorOut);'''
if old_decl not in h:
    raise SystemExit('confidence bridge declaration not found')
h = h.replace(old_decl, new_decl, 1)
bridge_h.write_text(h)

b = bridge_mm.read_text()
old_sig = '''const char *wm_prod_whisper_transcribe(const char *modelPath,
                                       const float *samples,
                                       int sampleCount,
                                       double *elapsedSeconds,
                                       float *confidenceOut,
                                       int *scoredTokenCountOut,
                                       char **errorOut) {
    if (errorOut) *errorOut = nullptr;
    if (confidenceOut) *confidenceOut = 0.0f;
    if (scoredTokenCountOut) *scoredTokenCountOut = 0;'''
new_sig = '''const char *wm_prod_whisper_transcribe(const char *modelPath,
                                       const float *samples,
                                       int sampleCount,
                                       double *elapsedSeconds,
                                       float *confidenceOut,
                                       int *scoredTokenCountOut,
                                       char **tokenDetailsOut,
                                       char **errorOut) {
    if (errorOut) *errorOut = nullptr;
    if (tokenDetailsOut) *tokenDetailsOut = nullptr;
    if (confidenceOut) *confidenceOut = 0.0f;
    if (scoredTokenCountOut) *scoredTokenCountOut = 0;'''
if old_sig not in b:
    raise SystemExit('confidence bridge signature not found')
b = b.replace(old_sig, new_sig, 1)

helper_marker = '''static char *wm_prod_copy_string(const std::string &value) {
    char *out = (char *)malloc(value.size() + 1);
    if (!out) return nullptr;
    memcpy(out, value.c_str(), value.size() + 1);
    return out;
}
'''
helper_plus = helper_marker + r'''
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
if helper_marker not in b:
    raise SystemExit('bridge copy helper not found')
b = b.replace(helper_marker, helper_plus, 1)

# Expand the domain prompt with the explicitly required manufacturers/terms.
prompt_re = re.compile(r'    params\.initial_prompt = "([^"]*)";\n')
m = prompt_re.search(b)
if not m:
    raise SystemExit('initial prompt not found')
existing_prompt = m.group(1)
required_prefix = 'Hager Siemens Siemens LOGO! Brüstungskanal VDE DIN VDE '
if 'Hager' not in existing_prompt or 'Siemens' not in existing_prompt:
    b = b[:m.start()] + f'    params.initial_prompt = "{required_prefix}{existing_prompt}";\n' + b[m.end():]

old_loop_start = '''    std::string result;
    double logProbabilitySum = 0.0;
    int scoredTokenCount = 0;'''
new_loop_start = '''    std::string result;
    std::string tokenDetails;
    double logProbabilitySum = 0.0;
    int scoredTokenCount = 0;'''
if old_loop_start not in b:
    raise SystemExit('confidence accumulator not found')
b = b.replace(old_loop_start, new_loop_start, 1)

old_scoring = '''            const float p = whisper_full_get_token_p(ctx, i, j);
            if (!std::isfinite(p) || p <= 0.0f) continue;
            const double bounded = std::max(1e-6, std::min(1.0, (double)p));
            logProbabilitySum += std::log(bounded);
            ++scoredTokenCount;'''
new_scoring = '''            const float p = whisper_full_get_token_p(ctx, i, j);
            if (!std::isfinite(p) || p <= 0.0f) continue;
            const double bounded = std::max(1e-6, std::min(1.0, (double)p));
            logProbabilitySum += std::log(bounded);
            ++scoredTokenCount;

            const char *tokenText = whisper_full_get_token_text(ctx, i, j);
            if (tokenText) {
                tokenDetails += std::to_string(bounded);
                tokenDetails += "\\t";
                tokenDetails += wm_prod_escape_token(tokenText);
                tokenDetails += "\\n";
            }'''
if old_scoring not in b:
    raise SystemExit('token scoring block not found')
b = b.replace(old_scoring, new_scoring, 1)

out_marker = '    if (scoredTokenCountOut) *scoredTokenCountOut = scoredTokenCount;\n\n    whisper_free(ctx);\n'
out_repl = '    if (scoredTokenCountOut) *scoredTokenCountOut = scoredTokenCount;\n    if (tokenDetailsOut) *tokenDetailsOut = wm_prod_copy_string(tokenDetails);\n\n    whisper_free(ctx);\n'
if out_marker not in b:
    raise SystemExit('confidence output marker not found')
b = b.replace(out_marker, out_repl, 1)
bridge_mm.write_text(b)

# Conservative German conversational cleanup. Technical normalization remains in GermanTranscriptNormalizer.
(app / 'GermanSpeechCleanup.swift').write_text(r'''import Foundation

enum GermanSpeechCleanup {
    static let version = "de-speech-v1"

    static func clean(_ input: String) -> String {
        var text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return text }

        // Remove hesitation fillers, not content words.
        text = replacing(text, pattern: #"(?i)(?<![\p{L}\p{N}])(?:ähm+|äh+)(?![\p{L}\p{N}])[, ]*"#, with: "")
        text = replacing(text, pattern: #"[ \t]+"#, with: " ")
        text = replacing(text, pattern: #"\s+([,.;:!?])"#, with: "$1")
        text = replacing(text, pattern: #"([,.;:!?])(?=[A-Za-zÄÖÜäöüß])"#, with: "$1 ")

        // Canonical forms explicitly required for the electrical/construction vocabulary.
        text = replacing(text, pattern: #"(?i)\bD\s*I\s*N\s+V\s*D\s*E\b"#, with: "DIN VDE")
        text = replacing(text, pattern: #"(?i)\bV\s*D\s*E\b"#, with: "VDE")
        text = replacing(text, pattern: #"(?i)\bhager\b"#, with: "Hager")
        text = replacing(text, pattern: #"(?i)\bsiemens\b"#, with: "Siemens")
        text = replacing(text, pattern: #"(?i)\bleistungsschutzschalter\b"#, with: "Leitungsschutzschalter")
        text = replacing(text, pattern: #"(?i)\bbr(?:ü|ue)stungs?\s*kanal\b"#, with: "Brüstungskanal")

        // Exact duplicated sentences are an ASR artifact; remove only adjacent identical copies.
        if let regex = try? NSRegularExpression(pattern: #"(?i)([^.!?]{12,}[.!?])\s+\1(?:\s+|$)"#) {
            for _ in 0..<3 {
                let range = NSRange(text.startIndex..<text.endIndex, in: text)
                let next = regex.stringByReplacingMatches(in: text, range: range, withTemplate: "$1 ")
                if next == text { break }
                text = next
            }
        }

        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func replacing(_ text: String, pattern: String, with replacement: String) -> String {
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return text }
        let range = NSRange(text.startIndex..<text.endIndex, in: text)
        return regex.stringByReplacingMatches(in: text, range: range, withTemplate: replacement)
    }
}
''')

# Replace recognizer Transcript/transcribe with word aggregation while keeping the verified 30 s chunks.
r = recognizer.read_text()
start = r.index('    struct Transcript {')
end = r.index('\n    private static func decodeTo16kMonoFloat', start)
new_recognizer = r'''    struct WordConfidence {
        let word: String
        let confidence: Double
    }

    struct Transcript {
        let text: String
        let confidence: Double
        let scoredTokens: Int
        let lowConfidenceWords: [WordConfidence]
    }

    private struct TokenPiece {
        let text: String
        let probability: Double
    }

    static func transcribe(url: URL, progress: ((Int, Int) -> Void)? = nil) throws -> Transcript {
        let samples = try decodeTo16kMonoFloat(url)
        guard !samples.isEmpty else { throw WhisperLocalRecognizerError.audioConvert("0 Samples") }
        guard let model = Bundle.main.url(forResource: "ggml-base", withExtension: "bin") else {
            throw WhisperLocalRecognizerError.modelMissing
        }

        let chunkSampleCount = Int(targetRate * 30.0)
        let totalChunks = max(1, Int(ceil(Double(samples.count) / Double(chunkSampleCount))))
        var parts: [String] = []
        var tokenPieces: [TokenPiece] = []
        var weightedLogProbability = 0.0
        var totalScoredTokens = 0

        for chunkIndex in 0..<totalChunks {
            let lower = chunkIndex * chunkSampleCount
            let upper = min(samples.count, lower + chunkSampleCount)
            let count = upper - lower
            if count <= 0 { continue }

            var elapsed: Double = 0
            var chunkConfidence: Float = 0
            var chunkScoredTokens: Int32 = 0
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
                        &chunkConfidence,
                        &chunkScoredTokens,
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
                tokenPieces.append(contentsOf: parseTokenDetails(details))
            }

            if chunkScoredTokens > 0, chunkConfidence > 0, chunkConfidence <= 1 {
                let tokens = Int(chunkScoredTokens)
                weightedLogProbability += log(max(Double(chunkConfidence), 1e-6)) * Double(tokens)
                totalScoredTokens += tokens
            }
            progress?(chunkIndex + 1, totalChunks)
        }

        let confidence = totalScoredTokens > 0
            ? exp(weightedLogProbability / Double(totalScoredTokens))
            : 0
        let merged = mergeChunkTexts(parts)
        let words = aggregateWords(tokenPieces)
        let lowWords = words.filter { $0.confidence < 0.45 }.prefix(12)
        return Transcript(
            text: merged,
            confidence: confidence,
            scoredTokens: totalScoredTokens,
            lowConfidenceWords: Array(lowWords)
        )
    }

    private static func parseTokenDetails(_ details: String) -> [TokenPiece] {
        var output: [TokenPiece] = []
        for line in details.split(separator: "\n", omittingEmptySubsequences: true) {
            let columns = line.split(separator: "\t", maxSplits: 1, omittingEmptySubsequences: false)
            guard columns.count == 2, let probability = Double(columns[0]), probability.isFinite else { continue }
            var token = String(columns[1])
            token = token.replacingOccurrences(of: "\\n", with: "\n")
            token = token.replacingOccurrences(of: "\\t", with: "\t")
            token = token.replacingOccurrences(of: "\\r", with: "\r")
            token = token.replacingOccurrences(of: "\\\\", with: "\\")
            output.append(TokenPiece(text: token, probability: max(0, min(1, probability))))
        }
        return output
    }

    private static func aggregateWords(_ pieces: [TokenPiece]) -> [WordConfidence] {
        var output: [WordConfidence] = []
        var current = ""
        var logSum = 0.0
        var count = 0

        func cleaned(_ value: String) -> String {
            value.trimmingCharacters(in: CharacterSet.whitespacesAndNewlines.union(.punctuationCharacters))
        }

        func flush() {
            let word = cleaned(current)
            if word.count > 1, count > 0 {
                output.append(WordConfidence(word: word, confidence: exp(logSum / Double(count))))
            }
            current = ""
            logSum = 0
            count = 0
        }

        for piece in pieces {
            let raw = piece.text
            if raw.hasPrefix("<|") { continue }
            let beginsNewWord = raw.first.map { $0.isWhitespace } ?? false
            if beginsNewWord && !current.isEmpty { flush() }
            let fragment = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            if fragment.isEmpty { continue }
            current += fragment
            logSum += log(max(piece.probability, 1e-6))
            count += 1
            if fragment.last.map({ ".,;:!?".contains($0) }) == true { flush() }
        }
        flush()
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
            if !remainder.isEmpty { merged += " " + remainder }
        }
        return merged.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func normalizedWord(_ word: String) -> String {
        word.lowercased().trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
    }
'''
r = r[:start] + new_recognizer + r[end:]
recognizer.write_text(r)

p = processor.read_text()
confidence_property = '    @Published private(set) var lastWhisperConfidence: Double? = nil\n'
if confidence_property not in p:
    raise SystemExit('lastWhisperConfidence property not found')
p = p.replace(confidence_property, confidence_property + '    @Published private(set) var lastLowConfidenceWordCount: Int = 0\n', 1)

old_meta_sig = '    private func updateSpeechMetadata(for sourceURL: URL, status: String, reason: String? = nil, partialText: String? = nil, whisperConfidence: Double? = nil, whisperScoredTokens: Int? = nil, normalizerVersion: String? = nil) throws -> URL {\n'
new_meta_sig = '    private func updateSpeechMetadata(for sourceURL: URL, status: String, reason: String? = nil, partialText: String? = nil, whisperConfidence: Double? = nil, whisperScoredTokens: Int? = nil, normalizerVersion: String? = nil, whisperLowConfidenceWords: [String]? = nil) throws -> URL {\n'
if old_meta_sig not in p:
    raise SystemExit('metadata confidence signature not found')
p = p.replace(old_meta_sig, new_meta_sig, 1)

meta_marker = '''        if let normalizerVersion = normalizerVersion {
            object["transcriptNormalizer"] = normalizerVersion
        }
'''
meta_replacement = meta_marker + '''        if let whisperLowConfidenceWords = whisperLowConfidenceWords, !whisperLowConfidenceWords.isEmpty {
            object["whisperLowConfidenceWords"] = whisperLowConfidenceWords
            object["whisperWordConfidenceThreshold"] = 0.45
        }
'''
if meta_marker not in p:
    raise SystemExit('normalizer metadata marker not found')
p = p.replace(meta_marker, meta_replacement, 1)

old_finish_sig = '    private func finishSuccess(item: TextQueueItem, sourceURL: URL, text: String, warnings: [String] = [], whisperConfidence: Double? = nil, whisperScoredTokens: Int? = nil, normalizerVersion: String? = nil) {\n'
new_finish_sig = '    private func finishSuccess(item: TextQueueItem, sourceURL: URL, text: String, warnings: [String] = [], whisperConfidence: Double? = nil, whisperScoredTokens: Int? = nil, normalizerVersion: String? = nil, whisperLowConfidenceWords: [String]? = nil) {\n'
if old_finish_sig not in p:
    raise SystemExit('finishSuccess confidence signature not found')
p = p.replace(old_finish_sig, new_finish_sig, 1)

old_success_call = '            _ = try updateSpeechMetadata(for: sourceURL, status: "recognized_complete", reason: warnings.isEmpty ? nil : warnings.joined(separator: " | "), whisperConfidence: whisperConfidence, whisperScoredTokens: whisperScoredTokens, normalizerVersion: normalizerVersion)\n'
new_success_call = '            _ = try updateSpeechMetadata(for: sourceURL, status: "recognized_complete", reason: warnings.isEmpty ? nil : warnings.joined(separator: " | "), whisperConfidence: whisperConfidence, whisperScoredTokens: whisperScoredTokens, normalizerVersion: normalizerVersion, whisperLowConfidenceWords: whisperLowConfidenceWords)\n'
if old_success_call not in p:
    raise SystemExit('success metadata confidence call not found')
p = p.replace(old_success_call, new_success_call, 1)

old_prod = '''            publishStatus("Whisper · DE Elektro · \\(item.sourceFileName)")
            DispatchQueue.main.async { self.lastWhisperConfidence = nil }
            let transcript = try WhisperLocalRecognizer.transcribe(url: sourceURL) { [weak self] done, total in
                self?.publishStatus("Whisper \\(done)/\\(total) · \\(item.sourceFileName)")
            }
            let text = GermanTranscriptNormalizer.normalize(transcript.text)
            DispatchQueue.main.async { self.lastWhisperConfidence = transcript.confidence }
            finishSuccess(
                item: item,
                sourceURL: sourceURL,
                text: text,
                warnings: [],
                whisperConfidence: transcript.confidence,
                whisperScoredTokens: transcript.scoredTokens,
                normalizerVersion: GermanTranscriptNormalizer.version
            )'''
new_prod = '''            publishStatus("Whisper · DE Elektro · \\(item.sourceFileName)")
            DispatchQueue.main.async {
                self.lastWhisperConfidence = nil
                self.lastLowConfidenceWordCount = 0
            }
            let transcript = try WhisperLocalRecognizer.transcribe(url: sourceURL) { [weak self] done, total in
                self?.publishStatus("Whisper \\(done)/\\(total) · \\(item.sourceFileName)")
            }
            let text = GermanSpeechCleanup.clean(GermanTranscriptNormalizer.normalize(transcript.text))
            let lowWords = transcript.lowConfidenceWords.map {
                "\\($0.word):\\(Int(($0.confidence * 100).rounded()))%"
            }
            DispatchQueue.main.async {
                self.lastWhisperConfidence = transcript.confidence
                self.lastLowConfidenceWordCount = transcript.lowConfidenceWords.count
            }
            finishSuccess(
                item: item,
                sourceURL: sourceURL,
                text: text,
                warnings: [],
                whisperConfidence: transcript.confidence,
                whisperScoredTokens: transcript.scoredTokens,
                normalizerVersion: GermanTranscriptNormalizer.version + "+" + GermanSpeechCleanup.version,
                whisperLowConfidenceWords: lowWords
            )'''
if old_prod not in p:
    raise SystemExit('v1.2.2 production block not found')
p = p.replace(old_prod, new_prod, 1)
processor.write_text(p)

c = content.read_text()
old_ui = '                info("cpu", "Whisper Base", model.processor.lastWhisperConfidence.map { "DE Elektro · Score \\(Int(($0 * 100).rounded()))%" } ?? "DE Elektro · offline", .green)\n'
new_ui = '''                info("cpu", "Whisper Base", model.processor.lastWhisperConfidence.map {
                    let score = Int(($0 * 100).rounded())
                    let low = model.processor.lastLowConfidenceWordCount
                    return low > 0 ? "DE Elektro · Score \\(score)% · \\(low) prüfen" : "DE Elektro · Score \\(score)%"
                } ?? "DE Elektro · offline", .green)
'''
if old_ui not in c:
    raise SystemExit('v1.2.2 confidence UI line not found')
c = c.replace(old_ui, new_ui, 1)
content.write_text(c)

subprocess.run(['/usr/libexec/PlistBuddy', '-c', 'Set :CFBundleShortVersionString 1.2.3', str(info)], check=True)
subprocess.run(['/usr/libexec/PlistBuddy', '-c', 'Set :CFBundleVersion 23', str(info)], check=True)

assert 'whisper_full_get_token_text(ctx, i, j)' in bridge_mm.read_text()
assert 'whisperLowConfidenceWords' in processor.read_text()
assert 'GermanSpeechCleanup.clean' in processor.read_text()
assert 'mergeChunkTexts' in recognizer.read_text()
print('v1.2.3 word confidence added: per-word low-confidence list + chunk dedup + German speech cleanup')
