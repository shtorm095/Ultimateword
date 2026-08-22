from pathlib import Path
import re
import subprocess

root = Path('/tmp/wmtext121-src')
app = root / 'WearMemoryText'
processor = app / 'TextProcessor.swift'
recognizer = app / 'WhisperLocalRecognizer.swift'
bridge_h = app / 'WMWhisperProductionBridge.h'
bridge_mm = app / 'WMWhisperProductionBridge.mm'
content = app / 'ContentView.swift'
info = app / 'Info.plist'

for path in (processor, recognizer, bridge_h, bridge_mm, content, info):
    if not path.exists():
        raise SystemExit(f'missing {path}')

bridge_h.write_text(r'''#import <Foundation/Foundation.h>

#ifdef __cplusplus
extern "C" {
#endif

const char * _Nullable wm_prod_whisper_transcribe(const char * _Nonnull modelPath,
                                                   const float * _Nonnull samples,
                                                   int sampleCount,
                                                   double * _Nullable elapsedSeconds,
                                                   float * _Nullable confidenceOut,
                                                   int * _Nullable scoredTokenCountOut,
                                                   char * _Nullable * _Nullable errorOut);
void wm_prod_whisper_free_string(const char * _Nullable value);

#ifdef __cplusplus
}
#endif
''')

bridge_mm.write_text(r'''#import "WMWhisperProductionBridge.h"
#include "whisper.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <string>

static char *wm_prod_copy_string(const std::string &value) {
    char *out = (char *)malloc(value.size() + 1);
    if (!out) return nullptr;
    memcpy(out, value.c_str(), value.size() + 1);
    return out;
}

const char *wm_prod_whisper_transcribe(const char *modelPath,
                                       const float *samples,
                                       int sampleCount,
                                       double *elapsedSeconds,
                                       float *confidenceOut,
                                       int *scoredTokenCountOut,
                                       char **errorOut) {
    if (errorOut) *errorOut = nullptr;
    if (confidenceOut) *confidenceOut = 0.0f;
    if (scoredTokenCountOut) *scoredTokenCountOut = 0;
    if (!modelPath || !samples || sampleCount <= 0) {
        if (errorOut) *errorOut = wm_prod_copy_string("Ungültige Audio- oder Modelldaten");
        return nullptr;
    }

    whisper_context_params cparams = whisper_context_default_params();
    cparams.use_gpu = false;
    cparams.flash_attn = false;
    whisper_context *ctx = whisper_init_from_file_with_params(modelPath, cparams);
    if (!ctx) {
        if (errorOut) *errorOut = wm_prod_copy_string("Whisper Base konnte nicht geladen werden");
        return nullptr;
    }

    whisper_full_params params = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    params.print_realtime = false;
    params.print_progress = false;
    params.print_timestamps = false;
    params.print_special = false;
    params.translate = false;
    params.language = "de";
    params.n_threads = 1;
    params.offset_ms = 0;
    params.no_context = true;
    params.single_segment = true;
    params.no_timestamps = true;
    params.suppress_blank = true;
    params.greedy.best_of = 1;
    params.temperature_inc = 0.0f;
    params.initial_prompt = "Elektrotechnik Elektroinstallation VDE RCD FI-Schalter LS-Schalter Leitungsschutzschalter Fehlerstrom-Schutzschalter Schutzleiter Neutralleiter Außenleiter Potentialausgleich Hauptpotentialausgleich Unterverteilung Hauptverteilung Kleinverteiler Reihenklemme Kabelrinne Kabelkanal Brüstungskanal Brandschott Funktionserhalt Stern-Dreieck Softstarter Frequenzumrichter Drehstrom Wechselstrom CEE-Steckdose Schuko-Steckdose NOT-AUS PV-Anlage Photovoltaik Wärmepumpe Wallbox TN-C-S VDE-AR-N 4100 DIN VDE 0100 DGUV Vorschrift 3 MLAR";

    const auto started = std::chrono::steady_clock::now();
    const int rc = whisper_full(ctx, params, samples, sampleCount);
    const auto finished = std::chrono::steady_clock::now();
    if (elapsedSeconds) {
        *elapsedSeconds = std::chrono::duration<double>(finished - started).count();
    }

    if (rc != 0) {
        whisper_free(ctx);
        if (errorOut) *errorOut = wm_prod_copy_string("Whisper konnte das Audio nicht verarbeiten");
        return nullptr;
    }

    std::string result;
    double logProbabilitySum = 0.0;
    int scoredTokenCount = 0;
    const whisper_token eot = whisper_token_eot(ctx);
    const int segmentCount = whisper_full_n_segments(ctx);
    for (int i = 0; i < segmentCount; ++i) {
        const char *text = whisper_full_get_segment_text(ctx, i);
        if (text) result += text;

        const int tokenCount = whisper_full_n_tokens(ctx, i);
        for (int j = 0; j < tokenCount; ++j) {
            const whisper_token token = whisper_full_get_token_id(ctx, i, j);
            if (token >= eot) continue;
            const float p = whisper_full_get_token_p(ctx, i, j);
            if (!std::isfinite(p) || p <= 0.0f) continue;
            const double bounded = std::max(1e-6, std::min(1.0, (double)p));
            logProbabilitySum += std::log(bounded);
            ++scoredTokenCount;
        }
    }

    if (confidenceOut && scoredTokenCount > 0) {
        *confidenceOut = (float)std::exp(logProbabilitySum / (double)scoredTokenCount);
    }
    if (scoredTokenCountOut) *scoredTokenCountOut = scoredTokenCount;

    whisper_free(ctx);

    while (!result.empty() && (result.front() == ' ' || result.front() == '\n' || result.front() == '\t')) result.erase(result.begin());
    while (!result.empty() && (result.back() == ' ' || result.back() == '\n' || result.back() == '\t')) result.pop_back();
    return wm_prod_copy_string(result);
}

void wm_prod_whisper_free_string(const char *value) {
    free((void *)value);
}
''')

normalizer = app / 'GermanTranscriptNormalizer.swift'
normalizer.write_text(r'''import Foundation

enum GermanTranscriptNormalizer {
    static let version = "de-electrical-v1"

    private static let replacements: [(String, String)] = [
        (#"(?i)\bFI\s*[- ]?\s*Schutzschalter\b"#, "FI-Schutzschalter"),
        (#"(?i)\bFI\s*[- ]?\s*Schalter\b"#, "FI-Schalter"),
        (#"(?i)\bRCD\s*[- ]?\s*Schalter\b"#, "RCD"),
        (#"(?i)\bLS\s*[- ]?\s*Schalter\b"#, "LS-Schalter"),
        (#"(?i)\bLeitung\s*schutz\s*schalter\b"#, "Leitungsschutzschalter"),
        (#"(?i)\bFehlerstrom\s*[- ]?\s*Schutzschalter\b"#, "Fehlerstrom-Schutzschalter"),
        (#"(?i)\bSchutz\s+Leiter\b"#, "Schutzleiter"),
        (#"(?i)\bNeutral\s+Leiter\b"#, "Neutralleiter"),
        (#"(?i)\bAußen\s+Leiter\b"#, "Außenleiter"),
        (#"(?i)\bHaupt\s+Potential\s*ausgleich\b"#, "Hauptpotentialausgleich"),
        (#"(?i)\bPotential\s+Ausgleich\b"#, "Potentialausgleich"),
        (#"(?i)\bUnter\s+Verteilung\b"#, "Unterverteilung"),
        (#"(?i)\bHaupt\s+Verteilung\b"#, "Hauptverteilung"),
        (#"(?i)\bKlein\s+Verteiler\b"#, "Kleinverteiler"),
        (#"(?i)\bReihen\s+Klemme\b"#, "Reihenklemme"),
        (#"(?i)\bKabel\s+Rinne\b"#, "Kabelrinne"),
        (#"(?i)\bKabel\s+Kanal\b"#, "Kabelkanal"),
        (#"(?i)\bBrüstungs\s+Kanal\b"#, "Brüstungskanal"),
        (#"(?i)\bBrand\s+Schott\b"#, "Brandschott"),
        (#"(?i)\bFunktions\s*erhalt\b"#, "Funktionserhalt"),
        (#"(?i)\bStern\s*[- ]?\s*Dreieck\b"#, "Stern-Dreieck"),
        (#"(?i)\bSoft\s+Starter\b"#, "Softstarter"),
        (#"(?i)\bFrequenz\s+Umrichter\b"#, "Frequenzumrichter"),
        (#"(?i)\bDreh\s+Strom\b"#, "Drehstrom"),
        (#"(?i)\bWechsel\s+Strom\b"#, "Wechselstrom"),
        (#"(?i)\bCEE\s*[- ]?\s*Steckdose\b"#, "CEE-Steckdose"),
        (#"(?i)\bSchuko\s*[- ]?\s*Steckdose\b"#, "Schuko-Steckdose"),
        (#"(?i)\bNOT\s*[- ]?\s*AUS\b"#, "NOT-AUS"),
        (#"(?i)\bPV\s*[- ]?\s*Anlage\b"#, "PV-Anlage"),
        (#"(?i)\bPhoto\s+Voltaik\b"#, "Photovoltaik"),
        (#"(?i)\bWärme\s+Pumpe\b"#, "Wärmepumpe"),
        (#"(?i)\bWall\s+Box\b"#, "Wallbox"),
        (#"(?i)\bTN\s*[- ]?\s*C\s*[- ]?\s*S\b"#, "TN-C-S"),
        (#"(?i)\bVDE\s*[- ]?\s*AR\s*[- ]?\s*N\s*4100\b"#, "VDE-AR-N 4100"),
        (#"(?i)\bDIN\s+VDE\s+0100\b"#, "DIN VDE 0100"),
        (#"(?i)\bDGUV\s+Vorschrift\s+3\b"#, "DGUV Vorschrift 3"),
        (#"(?i)\bM\s*L\s*A\s*R\b"#, "MLAR")
    ]

    static func normalize(_ input: String) -> String {
        var text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return text }

        text = replacing(text, pattern: #"\s+"#, with: " ")
        text = replacing(text, pattern: #"\s+([,.;:!?])"#, with: "$1")

        for (pattern, replacement) in replacements {
            text = replacing(text, pattern: pattern, with: replacement)
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

r = recognizer.read_text()
start = r.index('    static func transcribe(url: URL, progress: ((Int, Int) -> Void)? = nil) throws -> String {')
end = r.index('\n    private static func decodeTo16kMonoFloat', start)
new_transcribe = r'''    struct Transcript {
        let text: String
        let confidence: Double
        let scoredTokens: Int
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

p = processor.read_text()
property_marker = '    @Published private(set) var isProcessing = false\n'
if property_marker not in p:
    raise SystemExit('isProcessing property marker not found')
p = p.replace(property_marker, property_marker + '    @Published private(set) var lastWhisperConfidence: Double? = nil\n', 1)

old_meta_sig = '    private func updateSpeechMetadata(for sourceURL: URL, status: String, reason: String? = nil, partialText: String? = nil) throws -> URL {\n'
new_meta_sig = '    private func updateSpeechMetadata(for sourceURL: URL, status: String, reason: String? = nil, partialText: String? = nil, whisperConfidence: Double? = nil, whisperScoredTokens: Int? = nil, normalizerVersion: String? = nil) throws -> URL {\n'
if old_meta_sig not in p:
    raise SystemExit('updateSpeechMetadata signature not found')
p = p.replace(old_meta_sig, new_meta_sig, 1)

meta_marker = '        object["language"] = language.rawValue\n'
meta_insert = '''        object["language"] = language.rawValue
        if let whisperConfidence = whisperConfidence {
            object["whisperConfidence"] = max(0.0, min(1.0, whisperConfidence))
            object["whisperConfidenceMethod"] = "geometric_mean_token_probability"
            object["whisperModel"] = "base"
            object["whisperLanguage"] = "de"
        }
        if let whisperScoredTokens = whisperScoredTokens {
            object["whisperScoredTokens"] = whisperScoredTokens
        }
        if let normalizerVersion = normalizerVersion {
            object["transcriptNormalizer"] = normalizerVersion
        }
'''
if meta_marker not in p:
    raise SystemExit('metadata language marker not found')
p = p.replace(meta_marker, meta_insert, 1)

old_finish_sig = '    private func finishSuccess(item: TextQueueItem, sourceURL: URL, text: String, warnings: [String] = []) {\n'
new_finish_sig = '    private func finishSuccess(item: TextQueueItem, sourceURL: URL, text: String, warnings: [String] = [], whisperConfidence: Double? = nil, whisperScoredTokens: Int? = nil, normalizerVersion: String? = nil) {\n'
if old_finish_sig not in p:
    raise SystemExit('finishSuccess signature not found')
p = p.replace(old_finish_sig, new_finish_sig, 1)

old_success_meta = '            _ = try updateSpeechMetadata(for: sourceURL, status: "recognized_complete", reason: warnings.isEmpty ? nil : warnings.joined(separator: " | "))\n'
new_success_meta = '            _ = try updateSpeechMetadata(for: sourceURL, status: "recognized_complete", reason: warnings.isEmpty ? nil : warnings.joined(separator: " | "), whisperConfidence: whisperConfidence, whisperScoredTokens: whisperScoredTokens, normalizerVersion: normalizerVersion)\n'
if old_success_meta not in p:
    raise SystemExit('success metadata call not found')
p = p.replace(old_success_meta, new_success_meta, 1)

old_prod = '''            publishStatus("Whisper · \\(item.sourceFileName)")
            let text = try WhisperLocalRecognizer.transcribe(url: sourceURL) { [weak self] done, total in
                self?.publishStatus("Whisper \\(done)/\\(total) · \\(item.sourceFileName)")
            }
            finishSuccess(item: item, sourceURL: sourceURL, text: text, warnings: [])'''
new_prod = '''            publishStatus("Whisper · DE Elektro · \\(item.sourceFileName)")
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
if old_prod not in p:
    raise SystemExit('production Whisper block for confidence patch not found')
p = p.replace(old_prod, new_prod, 1)
processor.write_text(p)

c = content.read_text()
old_ui = '                info("cpu", "Whisper Base", "offline · CPU NoBLAS", .green)\n'
new_ui = '                info("cpu", "Whisper Base", model.processor.lastWhisperConfidence.map { "DE Elektro · Score \\(Int(($0 * 100).rounded()))%" } ?? "DE Elektro · offline", .green)\n'
if old_ui not in c:
    raise SystemExit('Whisper UI line not found')
c = c.replace(old_ui, new_ui, 1)
content.write_text(c)

subprocess.run(['/usr/libexec/PlistBuddy', '-c', 'Set :CFBundleShortVersionString 1.2.2', str(info)], check=True)
subprocess.run(['/usr/libexec/PlistBuddy', '-c', 'Set :CFBundleVersion 22', str(info)], check=True)

print('patched WearMemory Text 1.2.2: DE electrical prompt + deterministic normalizer + Whisper token confidence')
