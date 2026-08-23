from pathlib import Path
import plistlib
import re

root = Path('/tmp/wmtext121-src/WearMemoryText')
recognizer = root / 'WhisperLocalRecognizer.swift'
processor = root / 'TextProcessor.swift'
bridge_h = root / 'WMWhisperProductionBridge.h'
bridge_mm = root / 'WMWhisperProductionBridge.mm'
keeper = root / 'BackgroundExecutionKeeper.swift'
content = root / 'ContentView.swift'
info = root / 'Info.plist'

for path in (recognizer, processor, bridge_h, bridge_mm, keeper, content, info):
    if not path.exists():
        raise SystemExit(f'missing {path}')

# The previous 9-minute watchdog fired on a global queue, but then dispatched
# markNeedsPC back onto the same serial workQueue that was blocked inside
# synchronous whisper_full(). Therefore it could not actually interrupt local
# Whisper. v1.2.9 enforces the budget inside ggml via abort_callback.
#
# The budget is PROCESS CPU time, not wall-clock time. Time while iOS does not
# schedule the app is therefore not counted. Base and Small share one 540-second
# budget for the entire source M4A.
bridge_h.write_text(r'''#import <Foundation/Foundation.h>

#ifdef __cplusplus
extern "C" {
#endif

const char * _Nullable wm_prod_whisper_transcribe(const char * _Nonnull modelPath,
                                                   const float * _Nonnull samples,
                                                   int sampleCount,
                                                   double activeBudgetSeconds,
                                                   double * _Nullable activeSecondsOut,
                                                   int * _Nullable timedOutOut,
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
#include <cmath>
#include <cstring>
#include <string>
#include <time.h>

static char *wm_prod_copy_string(const std::string &value) {
    char *out = (char *)malloc(value.size() + 1);
    if (!out) return nullptr;
    memcpy(out, value.c_str(), value.size() + 1);
    return out;
}

static double wm_process_cpu_seconds(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &ts) != 0) return 0.0;
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1000000000.0;
}

struct WMWhisperBudget {
    double deadlineCPU;
    bool timedOut;
};

static bool wm_whisper_abort_callback(void *opaque) {
    WMWhisperBudget *budget = (WMWhisperBudget *)opaque;
    if (!budget) return false;
    if (wm_process_cpu_seconds() >= budget->deadlineCPU) {
        budget->timedOut = true;
        return true;
    }
    return false;
}

const char *wm_prod_whisper_transcribe(const char *modelPath,
                                       const float *samples,
                                       int sampleCount,
                                       double activeBudgetSeconds,
                                       double *activeSecondsOut,
                                       int *timedOutOut,
                                       float *confidenceOut,
                                       int *scoredTokenCountOut,
                                       char **errorOut) {
    if (errorOut) *errorOut = nullptr;
    if (activeSecondsOut) *activeSecondsOut = 0.0;
    if (timedOutOut) *timedOutOut = 0;
    if (confidenceOut) *confidenceOut = 0.0f;
    if (scoredTokenCountOut) *scoredTokenCountOut = 0;

    if (!modelPath || !samples || sampleCount <= 0) {
        if (errorOut) *errorOut = wm_prod_copy_string("Ungültige Audio- oder Modelldaten");
        return nullptr;
    }
    if (!(activeBudgetSeconds > 0.0)) {
        if (timedOutOut) *timedOutOut = 1;
        if (errorOut) *errorOut = wm_prod_copy_string("Aktives 9-Minuten-Limit erreicht");
        return nullptr;
    }

    const double startedCPU = wm_process_cpu_seconds();
    const double deadlineCPU = startedCPU + activeBudgetSeconds;

    whisper_context_params cparams = whisper_context_default_params();
    cparams.use_gpu = false;
    cparams.flash_attn = false;
    whisper_context *ctx = whisper_init_from_file_with_params(modelPath, cparams);
    if (!ctx) {
        if (activeSecondsOut) *activeSecondsOut = std::max(0.0, wm_process_cpu_seconds() - startedCPU);
        if (errorOut) *errorOut = wm_prod_copy_string("Whisper-Modell konnte nicht geladen werden");
        return nullptr;
    }

    // Model loading is part of the active work budget too.
    if (wm_process_cpu_seconds() >= deadlineCPU) {
        if (activeSecondsOut) *activeSecondsOut = std::max(0.0, wm_process_cpu_seconds() - startedCPU);
        if (timedOutOut) *timedOutOut = 1;
        whisper_free(ctx);
        if (errorOut) *errorOut = wm_prod_copy_string("Aktives 9-Minuten-Limit erreicht");
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

    WMWhisperBudget budget = { deadlineCPU, false };
    params.abort_callback = wm_whisper_abort_callback;
    params.abort_callback_user_data = &budget;

    const int rc = whisper_full(ctx, params, samples, sampleCount);
    const double finishedCPU = wm_process_cpu_seconds();
    if (activeSecondsOut) *activeSecondsOut = std::max(0.0, finishedCPU - startedCPU);

    if (budget.timedOut || finishedCPU >= deadlineCPU) {
        if (timedOutOut) *timedOutOut = 1;
        whisper_free(ctx);
        if (errorOut) *errorOut = wm_prod_copy_string("Aktives 9-Minuten-Limit erreicht");
        return nullptr;
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

r = recognizer.read_text()

# Distinct timeout error so TextProcessor's existing failure routing sends the
# original M4A to Audio Hören and never mistakes the abort for a clean result.
if '    case activeTimeout\n' not in r:
    marker = '    case whisper(String)\n'
    if marker not in r:
        raise SystemExit('WhisperLocalRecognizerError marker not found')
    r = r.replace(marker, marker + '    case activeTimeout\n', 1)

old_switch = '        case .whisper(let value): return value\n'
if old_switch not in r:
    raise SystemExit('WhisperLocalRecognizerError switch marker not found')
r = r.replace(old_switch, old_switch + '        case .activeTimeout: return "Общий лимит активной обработки на iPod: 9 минут"\n', 1)

old_struct = '''    struct Transcript {\n        let text: String\n        let confidence: Double\n        let scoredTokens: Int\n        let chunkTexts: [String]\n    }\n'''
new_struct = '''    struct Transcript {\n        let text: String\n        let confidence: Double\n        let scoredTokens: Int\n        let chunkTexts: [String]\n        let activeSeconds: Double\n    }\n'''
if old_struct not in r:
    raise SystemExit('Transcript struct with chunkTexts not found')
r = r.replace(old_struct, new_struct, 1)

old_sig = '    static func transcribe(url: URL, model selectedModel: Model, progress: ((Int, Int) -> Void)? = nil) throws -> Transcript {\n'
new_sig = '    static func transcribe(url: URL, model selectedModel: Model, activeBudgetSeconds: Double, progress: ((Int, Int) -> Void)? = nil) throws -> Transcript {\n'
if old_sig not in r:
    raise SystemExit('dual-pass transcribe signature not found')
r = r.replace(old_sig, new_sig, 1)

old_vars = '''        var parts: [String] = []\n        var chunkTexts = Array(repeating: "", count: totalChunks)\n        var weightedLogProbability = 0.0\n        var totalScoredTokens = 0\n'''
new_vars = '''        var parts: [String] = []\n        var chunkTexts = Array(repeating: "", count: totalChunks)\n        var weightedLogProbability = 0.0\n        var totalScoredTokens = 0\n        var activeSecondsUsed = 0.0\n'''
if old_vars not in r:
    raise SystemExit('recognizer accumulator marker not found')
r = r.replace(old_vars, new_vars, 1)

old_chunk = '''            var elapsed: Double = 0\n            var chunkConfidence: Float = 0\n            var chunkScoredTokens: Int32 = 0\n            var errorPointer: UnsafeMutablePointer<CChar>?\n            let resultPointer: UnsafePointer<CChar>? = modelURL.path.withCString { modelPath in\n                samples.withUnsafeBufferPointer { buffer in\n                    guard let base = buffer.baseAddress else { return nil }\n                    return wm_prod_whisper_transcribe(\n                        modelPath,\n                        base.advanced(by: lower),\n                        Int32(count),\n                        &elapsed,\n                        &chunkConfidence,\n                        &chunkScoredTokens,\n                        &errorPointer\n                    )\n                }\n            }\n\n            if let errorPointer {\n                let message = String(cString: errorPointer)\n                wm_prod_whisper_free_string(errorPointer)\n                throw WhisperLocalRecognizerError.whisper("\\(selectedModel.displayName) · Teil \\(chunkIndex + 1)/\\(totalChunks): \\(message)")\n            }\n'''
new_chunk = '''            let remainingActiveSeconds = activeBudgetSeconds - activeSecondsUsed\n            guard remainingActiveSeconds > 0 else {\n                throw WhisperLocalRecognizerError.activeTimeout\n            }\n\n            var chunkActiveSeconds: Double = 0\n            var timedOut: Int32 = 0\n            var chunkConfidence: Float = 0\n            var chunkScoredTokens: Int32 = 0\n            var errorPointer: UnsafeMutablePointer<CChar>?\n            let resultPointer: UnsafePointer<CChar>? = modelURL.path.withCString { modelPath in\n                samples.withUnsafeBufferPointer { buffer in\n                    guard let base = buffer.baseAddress else { return nil }\n                    return wm_prod_whisper_transcribe(\n                        modelPath,\n                        base.advanced(by: lower),\n                        Int32(count),\n                        remainingActiveSeconds,\n                        &chunkActiveSeconds,\n                        &timedOut,\n                        &chunkConfidence,\n                        &chunkScoredTokens,\n                        &errorPointer\n                    )\n                }\n            }\n            activeSecondsUsed += max(0, chunkActiveSeconds)\n\n            if timedOut != 0 {\n                if let errorPointer { wm_prod_whisper_free_string(errorPointer) }\n                throw WhisperLocalRecognizerError.activeTimeout\n            }\n            if let errorPointer {\n                let message = String(cString: errorPointer)\n                wm_prod_whisper_free_string(errorPointer)\n                throw WhisperLocalRecognizerError.whisper("\\(selectedModel.displayName) · Teil \\(chunkIndex + 1)/\\(totalChunks): \\(message)")\n            }\n'''
if old_chunk not in r:
    raise SystemExit('recognizer bridge call marker not found')
r = r.replace(old_chunk, new_chunk, 1)

old_return = '        return Transcript(text: text, confidence: confidence, scoredTokens: totalScoredTokens, chunkTexts: chunkTexts)\n'
new_return = '        return Transcript(text: text, confidence: confidence, scoredTokens: totalScoredTokens, chunkTexts: chunkTexts, activeSeconds: activeSecondsUsed)\n'
if old_return not in r:
    raise SystemExit('Transcript return marker not found')
r = r.replace(old_return, new_return, 1)
recognizer.write_text(r)

p = processor.read_text()

old_base = '''            let baseTranscript = try WhisperLocalRecognizer.transcribe(url: sourceURL, model: .base) { [weak self] done, total in\n                self?.publishStatus("Base 1/2 · \\(done)/\\(total) · \\(item.sourceFileName)")\n            }\n\n            publishStatus("Whisper Small Q5_1 · 2/2 · \\(item.sourceFileName)")\n            let smallTranscript = try WhisperLocalRecognizer.transcribe(url: sourceURL, model: .smallQ5_1) { [weak self] done, total in\n                self?.publishStatus("Small 2/2 · \\(done)/\\(total) · \\(item.sourceFileName)")\n            }\n'''
new_base = '''            let baseTranscript = try WhisperLocalRecognizer.transcribe(\n                url: sourceURL,\n                model: .base,\n                activeBudgetSeconds: maxFileProcessingSeconds\n            ) { [weak self] done, total in\n                self?.publishStatus("Base 1/2 · \\(done)/\\(total) · \\(item.sourceFileName)")\n            }\n\n            let remainingActiveSeconds = maxFileProcessingSeconds - baseTranscript.activeSeconds\n            guard remainingActiveSeconds > 0 else {\n                throw WhisperLocalRecognizerError.activeTimeout\n            }\n\n            publishStatus("Whisper Small Q5_1 · 2/2 · \\(item.sourceFileName)")\n            let smallTranscript = try WhisperLocalRecognizer.transcribe(\n                url: sourceURL,\n                model: .smallQ5_1,\n                activeBudgetSeconds: remainingActiveSeconds\n            ) { [weak self] done, total in\n                self?.publishStatus("Small 2/2 · \\(done)/\\(total) · \\(item.sourceFileName)")\n            }\n'''
if old_base not in p:
    raise SystemExit('Base -> Small production calls not found')
p = p.replace(old_base, new_base, 1)

# Disable the old wall-clock DispatchWorkItem. It could not preempt synchronous
# whisper_full and could later race with a completed result. The native active
# CPU watchdog above is now the only file deadline.
pattern = re.compile(
    r'    private func startFileDeadline\(item: TextQueueItem, sourceURL: URL\) \{.*?\n    \}\n\n    private func stopFileDeadline\(\) \{.*?\n    \}\n',
    re.S,
)
replacement = '''    private func startFileDeadline(item: TextQueueItem, sourceURL: URL) {\n        fileDeadlineWorkItem?.cancel()\n        fileDeadlineWorkItem = nil\n    }\n\n    private func stopFileDeadline() {\n        fileDeadlineWorkItem?.cancel()\n        fileDeadlineWorkItem = nil\n    }\n'''
p, count = pattern.subn(replacement, p, count=1)
if count != 1:
    raise SystemExit(f'old file deadline replacement count={count}')
processor.write_text(p)

# Text Keeper/FrontBoard is the verified background mechanism. Do not start
# silent audio or create a second in-process RunningBoard workaround.
keeper.write_text(r'''import Foundation

/// Background execution is provided externally by WearMemory Text Keeper,
/// which owns the FrontBoard foreground scene. This object intentionally does
/// nothing; it remains only to keep the existing TextAppModel wiring stable.
final class BackgroundExecutionKeeper {
    func start() {}
    func stop() {}
}
''')

with info.open('rb') as f:
    plist = plistlib.load(f)
modes = [value for value in plist.get('UIBackgroundModes', []) if value != 'audio']
if modes:
    plist['UIBackgroundModes'] = modes
else:
    plist.pop('UIBackgroundModes', None)
plist['CFBundleShortVersionString'] = '1.2.9'
plist['CFBundleVersion'] = '29'
with info.open('wb') as f:
    plistlib.dump(plist, f, fmt=plistlib.FMT_XML, sort_keys=False)

c = content.read_text()
c = c.replace('info("timer", "Лимит файла", "9 минут", .cyan)', 'info("timer", "Лимит файла", "9 минут работы", .cyan)', 1)
content.write_text(c)

# Build-time invariants.
checks = {
    bridge_mm: [
        'CLOCK_PROCESS_CPUTIME_ID',
        'params.abort_callback = wm_whisper_abort_callback',
        'Aktives 9-Minuten-Limit erreicht',
    ],
    recognizer: [
        'case activeTimeout',
        'activeBudgetSeconds: Double',
        'let activeSeconds: Double',
        'activeSecondsUsed += max(0, chunkActiveSeconds)',
    ],
    processor: [
        'activeBudgetSeconds: maxFileProcessingSeconds',
        'maxFileProcessingSeconds - baseTranscript.activeSeconds',
        'fileDeadlineWorkItem = nil',
    ],
    content: ['9 минут работы'],
}
for path, needles in checks.items():
    text = path.read_text()
    for needle in needles:
        if needle not in text:
            raise SystemExit(f'missing invariant {needle!r} in {path.name}')

print('patched WearMemory Text 1.2.9: Text Keeper background + real 9-minute active CPU watchdog')
