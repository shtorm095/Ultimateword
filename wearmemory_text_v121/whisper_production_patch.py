from pathlib import Path
import re

source = Path(__file__).with_name("whisper_production_patch_original.py")
code = source.read_text()
pattern = re.compile(
    r"start_marker = .*?\nstart = t\.find\(start_marker\)\nif start < 0:\n    raise SystemExit\('process recognition start marker not found'\)\n",
    re.S,
)
replacement = """start = t.find('            splitIntoPieces(sourceURL)')
if start < 0:
    raise SystemExit('process recognition start marker not found')
"""
code, count = pattern.subn(lambda _: replacement, code, count=1)
if count != 1:
    raise SystemExit(f'expected one start-marker block, found {count}')
exec(compile(code, str(source), 'exec'), {'__file__': str(source), '__name__': '__main__'})

root = Path('/tmp/wmtext121-src')
app = root / 'WearMemoryText'
recognizer = app / 'WhisperLocalRecognizer.swift'
processor = app / 'TextProcessor.swift'

r = recognizer.read_text()
start = r.index('    static func transcribe(url: URL) throws -> String {')
end = r.index('\n    private static func decodeTo16kMonoFloat', start)
chunked = r'''    static func transcribe(url: URL, progress: ((Int, Int) -> Void)? = nil) throws -> String {
        let samples = try decodeTo16kMonoFloat(url)
        guard !samples.isEmpty else { throw WhisperLocalRecognizerError.audioConvert("0 Samples") }
        guard let model = Bundle.main.url(forResource: "ggml-base", withExtension: "bin") else {
            throw WhisperLocalRecognizerError.modelMissing
        }

        let chunkSampleCount = Int(targetRate * 30.0)
        let totalChunks = max(1, Int(ceil(Double(samples.count) / Double(chunkSampleCount))))
        var parts: [String] = []

        for chunkIndex in 0..<totalChunks {
            let lower = chunkIndex * chunkSampleCount
            let upper = min(samples.count, lower + chunkSampleCount)
            let count = upper - lower
            if count <= 0 { continue }

            var elapsed: Double = 0
            var errorPointer: UnsafeMutablePointer<CChar>?
            let resultPointer: UnsafePointer<CChar>? = model.path.withCString { modelPath in
                samples.withUnsafeBufferPointer { buffer in
                    guard let base = buffer.baseAddress else { return nil }
                    return wm_prod_whisper_transcribe(
                        modelPath,
                        base.advanced(by: lower),
                        Int32(count),
                        &elapsed,
                        &errorPointer
                    )
                }
            }

            if let errorPointer {
                let message = String(cString: errorPointer)
                wm_prod_whisper_free_string(errorPointer)
                throw WhisperLocalRecognizerError.whisper("Teil \(chunkIndex + 1)/\(totalChunks): \(message)")
            }
            guard let resultPointer else {
                throw WhisperLocalRecognizerError.whisper("Teil \(chunkIndex + 1)/\(totalChunks): kein Ergebnis")
            }
            let text = String(cString: resultPointer).trimmingCharacters(in: .whitespacesAndNewlines)
            wm_prod_whisper_free_string(resultPointer)
            if !text.isEmpty { parts.append(text) }
            progress?(chunkIndex + 1, totalChunks)
        }

        return parts.joined(separator: " ").trimmingCharacters(in: .whitespacesAndNewlines)
    }
'''
r = r[:start] + chunked + r[end:]
recognizer.write_text(r)

p = processor.read_text()
old = '''            publishStatus("Whisper Base · Deutsch · offline")
            let text = try WhisperLocalRecognizer.transcribe(url: sourceURL)
            finishSuccess(item: item, sourceURL: sourceURL, text: text, warnings: [])'''
new = '''            publishStatus("Whisper · \(item.sourceFileName)")
            let text = try WhisperLocalRecognizer.transcribe(url: sourceURL) { [weak self] done, total in
                self?.publishStatus("Whisper \(done)/\(total) · \(item.sourceFileName)")
            }
            finishSuccess(item: item, sourceURL: sourceURL, text: text, warnings: [])'''
if old not in p:
    raise SystemExit('production Whisper block not found')
p = p.replace(old, new, 1)
processor.write_text(p)

saving_patch = Path(__file__).with_name("saving_contract_patch.py")
saving_code = saving_patch.read_text()
exec(compile(saving_code, str(saving_patch), 'exec'), {'__file__': str(saving_patch), '__name__': '__main__'})

german_patch = Path(__file__).with_name("german_domain_patch.py")
german_code = german_patch.read_text()
exec(compile(german_code, str(german_patch), 'exec'), {'__file__': str(german_patch), '__name__': '__main__'})

speaker_patch = Path(__file__).with_name("speaker_diarization_patch.py")
speaker_code = speaker_patch.read_text()
exec(compile(speaker_code, str(speaker_patch), 'exec'), {'__file__': str(speaker_patch), '__name__': '__main__'})

print('patched WearMemory Text 1.2.1: saving contract + German technical correction + token confidence + conservative speaker separation')
