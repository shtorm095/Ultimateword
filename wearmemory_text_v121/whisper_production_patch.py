from pathlib import Path
import re
import subprocess

root = Path('/tmp/wmtext121-src')
app = root / 'WearMemoryText'
processor = app / 'TextProcessor.swift'
content = app / 'ContentView.swift'
project = root / 'project.yml'
info = app / 'Info.plist'

for p in (processor, content, project, info):
    if not p.exists():
        raise SystemExit(f'missing {p}')

# Native bridge: same safe Whisper path that was validated on the iPod,
# but without diagnostic UI or test stages.
(app / 'WMWhisperProductionBridge.h').write_text(r'''#import <Foundation/Foundation.h>

#ifdef __cplusplus
extern "C" {
#endif

const char * _Nullable wm_prod_whisper_transcribe(const char * _Nonnull modelPath,
                                                   const float * _Nonnull samples,
                                                   int sampleCount,
                                                   double * _Nullable elapsedSeconds,
                                                   char * _Nullable * _Nullable errorOut);
void wm_prod_whisper_free_string(const char * _Nullable value);

#ifdef __cplusplus
}
#endif
''')

(app / 'WMWhisperProductionBridge.mm').write_text(r'''#import "WMWhisperProductionBridge.h"
#include "whisper.h"
#include <chrono>
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
                                       char **errorOut) {
    if (errorOut) *errorOut = nullptr;
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
    const int count = whisper_full_n_segments(ctx);
    for (int i = 0; i < count; ++i) {
        const char *text = whisper_full_get_segment_text(ctx, i);
        if (text) result += text;
    }
    whisper_free(ctx);

    while (!result.empty() && (result.front() == ' ' || result.front() == '\n' || result.front() == '\t')) result.erase(result.begin());
    while (!result.empty() && (result.back() == ' ' || result.back() == '\n' || result.back() == '\t')) result.pop_back();
    return wm_prod_copy_string(result);
}

void wm_prod_whisper_free_string(const char *value) {
    free((void *)value);
}
''')

(app / 'WMWhisper-Bridging-Header.h').write_text('#import "WMWhisperProductionBridge.h"\n')

(app / 'WhisperLocalRecognizer.swift').write_text(r'''import Foundation
import AudioToolbox

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

    static func transcribe(url: URL) throws -> String {
        let samples = try decodeTo16kMonoFloat(url)
        guard !samples.isEmpty else { throw WhisperLocalRecognizerError.audioConvert("0 Samples") }
        guard let model = Bundle.main.url(forResource: "ggml-base", withExtension: "bin") else {
            throw WhisperLocalRecognizerError.modelMissing
        }

        var elapsed: Double = 0
        var errorPointer: UnsafeMutablePointer<CChar>?
        let resultPointer: UnsafePointer<CChar>? = model.path.withCString { modelPath in
            samples.withUnsafeBufferPointer { buffer in
                wm_prod_whisper_transcribe(modelPath, buffer.baseAddress!, Int32(buffer.count), &elapsed, &errorPointer)
            }
        }

        if let errorPointer {
            let message = String(cString: errorPointer)
            wm_prod_whisper_free_string(errorPointer)
            throw WhisperLocalRecognizerError.whisper(message)
        }
        guard let resultPointer else { throw WhisperLocalRecognizerError.whisper("Whisper hat kein Ergebnis geliefert") }
        let text = String(cString: resultPointer).trimmingCharacters(in: .whitespacesAndNewlines)
        wm_prod_whisper_free_string(resultPointer)
        return text
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

# TextProcessor: keep queue, metadata, TXT and Drive pipeline intact, but make
# local Whisper the production recognizer. Old Apple Speech routines remain
# compiled for now but are no longer entered.
t = processor.read_text()

auth_guard = '''        guard speechAuthorization == .authorized else {
            publishStatus("Нужно разрешение Speech")
            return
        }
'''
if auth_guard not in t:
    raise SystemExit('Speech authorization guard not found')
t = t.replace(auth_guard, '', 1)

# Do not trigger an iOS Speech permission dialog anymore.
pattern = re.compile(r'    func requestAuthorization\(completion: \(\(\) -> Void\)\? = nil\) \{.*?\n    \}\n\n    func refreshQueue', re.S)
replacement = '''    func requestAuthorization(completion: (() -> Void)? = nil) {
        DispatchQueue.main.async {
            self.statusText = "Whisper Base · Deutsch · offline"
            completion?()
        }
    }

    func refreshQueue'''
t, count = pattern.subn(replacement, t, count=1)
if count != 1:
    raise SystemExit('requestAuthorization block not replaced')

start_marker = '            publishStatus("Распознаю \\(item.sourceFileName)")'
start = t.find(start_marker)
if start < 0:
    raise SystemExit('process recognition start marker not found')
end_marker = '\n        } catch {\n            finishFailure(itemID: item.id, message: error.localizedDescription)'
end = t.find(end_marker, start)
if end < 0:
    raise SystemExit('process recognition end marker not found')
production_block = '''            publishStatus("Whisper Base · Deutsch · offline")
            let text = try WhisperLocalRecognizer.transcribe(url: sourceURL)
            finishSuccess(item: item, sourceURL: sourceURL, text: text, warnings: [])'''
t = t[:start] + production_block + t[end:]
processor.write_text(t)

# UI: no diagnostic/lab tab, no Speech permission dependency, German-only.
c = content.read_text()
language_block = re.compile(
    r'                HStack \{\n                    Image\(systemName: "character\.book\.closed\.fill"\).*?\n                \}\n                Divider\(\)\.background\(Color\.white\.opacity\(0\.08\)\)\n',
    re.S
)
language_replacement = '''                info("character.book.closed.fill", "Язык", "Deutsch (de)", .purple)
                Divider().background(Color.white.opacity(0.08))
'''
c, count = language_block.subn(language_replacement, c, count=1)
if count != 1:
    raise SystemExit('language picker block not replaced')

speech_line = '                info("checkmark.circle.fill", "Speech", speechText, model.processor.speechAuthorization == .authorized ? .green : .orange)'
if speech_line not in c:
    raise SystemExit('Speech UI line not found')
c = c.replace(speech_line, '                info("cpu", "Whisper Base", "offline · CPU NoBLAS", .green)', 1)

old_disabled = '                .disabled(model.processor.speechAuthorization != .authorized || model.processor.isProcessing)'
if old_disabled not in c:
    raise SystemExit('Speech-dependent button state not found')
c = c.replace(old_disabled, '                .disabled(model.processor.isProcessing)', 1)

speech_var = re.compile(r'\n    private var speechText: String \{.*?\n    \}\n\n    private func screen', re.S)
c, count = speech_var.subn('\n    private func screen', c, count=1)
if count != 1:
    raise SystemExit('speechText helper not removed')
content.write_text(c)

# Xcode: bridge + exact CPU-only/no-BLAS static library.
p = project.read_text()
needle = "        IPHONEOS_DEPLOYMENT_TARGET: '15.0'\n"
if needle not in p:
    raise SystemExit('deployment target setting not found')
insert = needle + "        SWIFT_OBJC_BRIDGING_HEADER: WearMemoryText/WMWhisper-Bridging-Header.h\n        HEADER_SEARCH_PATHS: '$(inherited) /tmp/wmtext121-native/include'\n        LIBRARY_SEARCH_PATHS: '$(inherited) /tmp/wmtext121-native/lib'\n        OTHER_LDFLAGS: '$(inherited) -lwmwhisper -lc++'\n"
p = p.replace(needle, insert, 1)
project.write_text(p)

subprocess.run(['/usr/libexec/PlistBuddy', '-c', 'Set :CFBundleShortVersionString 1.2.1', str(info)], check=True)
subprocess.run(['/usr/libexec/PlistBuddy', '-c', 'Set :CFBundleVersion 21', str(info)], check=True)

print('patched WearMemory Text 1.2.1 production Whisper Base CPU NoBLAS')
