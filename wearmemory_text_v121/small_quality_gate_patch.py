from pathlib import Path

root = Path('/tmp/wmtext121-src/WearMemoryText')
recognizer = root / 'WhisperLocalRecognizer.swift'
processor = root / 'TextProcessor.swift'

for path in (recognizer, processor):
    if not path.exists():
        raise SystemExit(f'missing {path}')

# Keep one aligned text slot for every 30-second Whisper chunk. This lets the
# Base and Small passes be compared chunk-for-chunk without guessing from a
# global confidence percentage.
r = recognizer.read_text()
old_struct = '''    struct Transcript {\n        let text: String\n        let confidence: Double\n        let scoredTokens: Int\n    }\n'''
new_struct = '''    struct Transcript {\n        let text: String\n        let confidence: Double\n        let scoredTokens: Int\n        let chunkTexts: [String]\n    }\n'''
if old_struct not in r:
    raise SystemExit('Transcript struct marker not found')
r = r.replace(old_struct, new_struct, 1)

old_parts = '''        var parts: [String] = []\n        var weightedLogProbability = 0.0\n'''
new_parts = '''        var parts: [String] = []\n        var chunkTexts = Array(repeating: "", count: totalChunks)\n        var weightedLogProbability = 0.0\n'''
if old_parts not in r:
    raise SystemExit('chunk array insertion marker not found')
r = r.replace(old_parts, new_parts, 1)

old_text = '''            let text = String(cString: resultPointer).trimmingCharacters(in: .whitespacesAndNewlines)\n            wm_prod_whisper_free_string(resultPointer)\n            if !text.isEmpty { parts.append(text) }\n'''
new_text = '''            let text = String(cString: resultPointer).trimmingCharacters(in: .whitespacesAndNewlines)\n            wm_prod_whisper_free_string(resultPointer)\n            chunkTexts[chunkIndex] = text\n            if !text.isEmpty { parts.append(text) }\n'''
if old_text not in r:
    raise SystemExit('chunk text capture marker not found')
r = r.replace(old_text, new_text, 1)

old_return = '        return Transcript(text: text, confidence: confidence, scoredTokens: totalScoredTokens)\n'
new_return = '        return Transcript(text: text, confidence: confidence, scoredTokens: totalScoredTokens, chunkTexts: chunkTexts)\n'
if old_return not in r:
    raise SystemExit('Transcript return marker not found')
r = r.replace(old_return, new_return, 1)
recognizer.write_text(r)

# Conservative quality gate for the final Small pass:
# - both model passes must report the same 30-second chunk count;
# - if Base found speech in a chunk, Small must not return that same chunk empty.
# A thrown Small error is already routed to needs_pc/Audio Hören by the existing
# failure path, so this patch handles silent/incomplete successful returns.
p = processor.read_text()
old_finish = '''            let text = GermanTranscriptNormalizer.normalize(smallTranscript.text)\n            DispatchQueue.main.async { self.lastWhisperConfidence = smallTranscript.confidence }\n            finishSuccess(\n                item: item,\n                sourceURL: sourceURL,\n                text: text,\n                warnings: [],\n                whisperConfidence: smallTranscript.confidence,\n                whisperScoredTokens: smallTranscript.scoredTokens,\n                normalizerVersion: GermanTranscriptNormalizer.version\n            )'''
new_finish = '''            let text = GermanTranscriptNormalizer.normalize(smallTranscript.text)\n            DispatchQueue.main.async { self.lastWhisperConfidence = smallTranscript.confidence }\n\n            var qualityWarnings: [String] = []\n            if baseTranscript.chunkTexts.count != smallTranscript.chunkTexts.count {\n                qualityWarnings.append(\n                    "Small Q5_1: неполный проход (Base \\(baseTranscript.chunkTexts.count) блоков, Small \\(smallTranscript.chunkTexts.count))"\n                )\n            }\n\n            let comparableChunks = min(baseTranscript.chunkTexts.count, smallTranscript.chunkTexts.count)\n            var missingSmallChunks: [Int] = []\n            if comparableChunks > 0 {\n                for index in 0..<comparableChunks {\n                    let baseText = baseTranscript.chunkTexts[index].trimmingCharacters(in: .whitespacesAndNewlines)\n                    let smallText = smallTranscript.chunkTexts[index].trimmingCharacters(in: .whitespacesAndNewlines)\n                    if !baseText.isEmpty && smallText.isEmpty {\n                        missingSmallChunks.append(index + 1)\n                    }\n                }\n            }\n            if !missingSmallChunks.isEmpty {\n                let blocks = missingSmallChunks.map(String.init).joined(separator: ",")\n                qualityWarnings.append("Small Q5_1: пустой результат в блоках \\(blocks), где Base распознал речь")\n            }\n\n            finishSuccess(\n                item: item,\n                sourceURL: sourceURL,\n                text: text,\n                warnings: qualityWarnings,\n                whisperConfidence: smallTranscript.confidence,\n                whisperScoredTokens: smallTranscript.scoredTokens,\n                normalizerVersion: GermanTranscriptNormalizer.version\n            )'''
if old_finish not in p:
    raise SystemExit('dual-pass finish block after routing patch not found')
p = p.replace(old_finish, new_finish, 1)

for required in (
    'let chunkTexts: [String]',
    'baseTranscript.chunkTexts.count != smallTranscript.chunkTexts.count',
    'if !baseText.isEmpty && smallText.isEmpty',
    'warnings: qualityWarnings',
):
    target = r if required == 'let chunkTexts: [String]' else p
    if required not in target:
        raise SystemExit(f'quality gate invariant missing: {required}')

processor.write_text(p)
print('patched: Small Q5_1 chunk-quality gate routes incomplete transcription to Audio Hören')
