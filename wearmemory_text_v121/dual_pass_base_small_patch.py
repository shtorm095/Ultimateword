from pathlib import Path
import subprocess

root = Path('/tmp/wmtext121-src')
app = root / 'WearMemoryText'
recognizer = app / 'WhisperLocalRecognizer.swift'
processor = app / 'TextProcessor.swift'
bridge_mm = app / 'WMWhisperProductionBridge.mm'
content = app / 'ContentView.swift'
info = app / 'Info.plist'

for path in (recognizer, processor, bridge_mm, content, info):
    if not path.exists():
        raise SystemExit(f'missing {path}')

# Replace the single-model recognizer with an explicit Base -> Small Q5_1 capable recognizer.
r = recognizer.read_text()
start = r.index('    static func transcribe(url: URL, progress: ((Int, Int) -> Void)? = nil) throws -> Transcript {')
end = r.index('\n    private static func decodeTo16kMonoFloat', start)
new_transcribe = r'''    enum Model {
        case base
        case smallQ5_1

        var resourceName: String {
            switch self {
            case .base: return "ggml-base"
            case .smallQ5_1: return "ggml-small-q5_1"
            }
        }

        var displayName: String {
            switch self {
            case .base: return "Base"
            case .smallQ5_1: return "Small Q5_1"
            }
        }
    }

    static func transcribe(url: URL, model selectedModel: Model, progress: ((Int, Int) -> Void)? = nil) throws -> Transcript {
        let samples = try decodeTo16kMonoFloat(url)
        guard !samples.isEmpty else { throw WhisperLocalRecognizerError.audioConvert("0 Samples") }
        guard let modelURL = Bundle.main.url(forResource: selectedModel.resourceName, withExtension: "bin") else {
            throw WhisperLocalRecognizerError.modelMissing
        }

        let chunkSampleCount = Int(targetRate * 30.0)
        let totalChunks = max(1, Int(ceil(Double(samples.count) / Double(chunkSampleCount))))
        var parts: [String] = []
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
            var errorPointer: UnsafeMutablePointer<CChar>?
            let resultPointer: UnsafePointer<CChar>? = modelURL.path.withCString { modelPath in
                samples.withUnsafeBufferPointer { buffer in
                    guard let base = buffer.baseAddress else { return nil }
                    return wm_prod_whisper_transcribe(
                        modelPath,
                        base.advanced(by: lower),
                        Int32(count),
                        &elapsed,
                        &chunkConfidence,
                        &chunkScoredTokens,
                        &errorPointer
                    )
                }
            }

            if let errorPointer {
                let message = String(cString: errorPointer)
                wm_prod_whisper_free_string(errorPointer)
                throw WhisperLocalRecognizerError.whisper("\(selectedModel.displayName) · Teil \(chunkIndex + 1)/\(totalChunks): \(message)")
            }
            guard let resultPointer else {
                throw WhisperLocalRecognizerError.whisper("\(selectedModel.displayName) · Teil \(chunkIndex + 1)/\(totalChunks): kein Ergebnis")
            }

            let text = String(cString: resultPointer).trimmingCharacters(in: .whitespacesAndNewlines)
            wm_prod_whisper_free_string(resultPointer)
            if !text.isEmpty { parts.append(text) }

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
        let text = parts.joined(separator: " ").trimmingCharacters(in: .whitespacesAndNewlines)
        return Transcript(text: text, confidence: confidence, scoredTokens: totalScoredTokens)
    }
'''
r = r[:start] + new_transcribe + r[end:]
recognizer.write_text(r)

# Run the complete audio first through Base, then through Small Q5_1.
p = processor.read_text()
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
new_prod = '''            publishStatus("Whisper Base · 1/2 · \\(item.sourceFileName)")
            DispatchQueue.main.async { self.lastWhisperConfidence = nil }
            let baseTranscript = try WhisperLocalRecognizer.transcribe(url: sourceURL, model: .base) { [weak self] done, total in
                self?.publishStatus("Base 1/2 · \\(done)/\\(total) · \\(item.sourceFileName)")
            }

            publishStatus("Whisper Small Q5_1 · 2/2 · \\(item.sourceFileName)")
            let smallTranscript = try WhisperLocalRecognizer.transcribe(url: sourceURL, model: .smallQ5_1) { [weak self] done, total in
                self?.publishStatus("Small 2/2 · \\(done)/\\(total) · \\(item.sourceFileName)")
            }

            let text = GermanTranscriptNormalizer.normalize(smallTranscript.text)
            DispatchQueue.main.async { self.lastWhisperConfidence = smallTranscript.confidence }
            let baseSummary = "Base score \\(Int((baseTranscript.confidence * 100).rounded()))%"
            finishSuccess(
                item: item,
                sourceURL: sourceURL,
                text: text,
                warnings: [baseSummary],
                whisperConfidence: smallTranscript.confidence,
                whisperScoredTokens: smallTranscript.scoredTokens,
                normalizerVersion: GermanTranscriptNormalizer.version
            )'''
if old_prod not in p:
    raise SystemExit('1.2.2 production block not found')
p = p.replace(old_prod, new_prod, 1)

# Metadata should describe the final recognizer and the cascade.
if 'object["whisperModel"] = "base"' not in p:
    raise SystemExit('whisperModel metadata marker not found')
p = p.replace('object["whisperModel"] = "base"', 'object["whisperModel"] = "small-q5_1"\n            object["whisperCascade"] = "base->small-q5_1"', 1)
processor.write_text(p)

# Generic bridge error, because the same bridge now loads two different model files.
b = bridge_mm.read_text()
b = b.replace('Whisper Base konnte nicht geladen werden', 'Whisper-Modell konnte nicht geladen werden')
bridge_mm.write_text(b)

# Reflect the cascade in the UI without changing the existing confidence display contract.
c = content.read_text()
old_ui = '                info("cpu", "Whisper Base", model.processor.lastWhisperConfidence.map { "DE Elektro · Score \\(Int(($0 * 100).rounded()))%" } ?? "DE Elektro · offline", .green)\n'
new_ui = '                info("cpu", "Base → Small Q5_1", model.processor.lastWhisperConfidence.map { "DE Elektro · Score \\(Int(($0 * 100).rounded()))%" } ?? "2-pass · offline", .green)\n'
if old_ui not in c:
    raise SystemExit('1.2.2 Whisper UI marker not found')
c = c.replace(old_ui, new_ui, 1)
content.write_text(c)

subprocess.run(['/usr/libexec/PlistBuddy', '-c', 'Set :CFBundleShortVersionString 1.2.4', str(info)], check=True)
subprocess.run(['/usr/libexec/PlistBuddy', '-c', 'Set :CFBundleVersion 24', str(info)], check=True)

print('patched WearMemory Text 1.2.4: full-file dual pass Base -> Small Q5_1')
