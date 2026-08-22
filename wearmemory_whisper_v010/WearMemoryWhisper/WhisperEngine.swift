import Foundation
import AVFoundation
import AudioToolbox

struct WhisperRunResult {
    let sourceName: String
    let text: String
    let audioSeconds: Double
    let processingSeconds: Double
    let outputURL: URL
}

struct AudioProbeResult {
    let sourceName: String
    let audioSeconds: Double
    let sampleCount: Int
}

struct ModelProbeResult {
    let loadSeconds: Double
}

enum WhisperEngineError: LocalizedError {
    case noSharedContainer, noAudio, modelMissing
    case audioOpen(String), audioConvert(String), whisper(String)
    var errorDescription: String? {
        switch self {
        case .noSharedContainer: return "Gemeinsamer WearMemory-Speicher ist nicht verfügbar."
        case .noAudio: return "Kein M4A in AudioInbox gefunden."
        case .modelMissing: return "Whisper Base Modell fehlt."
        case .audioOpen(let v): return "M4A konnte nicht geöffnet werden: \(v)"
        case .audioConvert(let v): return "Audio-Konvertierung fehlgeschlagen: \(v)"
        case .whisper(let v): return "Whisper: \(v)"
        }
    }
}

final class WhisperEngine {
    static let appGroup = "group.local.pavel.WearMemory"
    static let targetRate: Double = 16_000
    static let stageKey = "WMWhisperLastStage"

    static func setStage(_ value: String) {
        UserDefaults.standard.set(value, forKey: stageKey)
        UserDefaults.standard.synchronize()
    }

    static func lastStage() -> String {
        UserDefaults.standard.string(forKey: stageKey) ?? "Noch kein Lauf"
    }

    private func modelURL() throws -> URL {
        guard let model = Bundle.main.url(forResource: "ggml-base", withExtension: "bin") else {
            throw WhisperEngineError.modelMissing
        }
        return model
    }

    func latestAudioURL() throws -> URL {
        Self.setStage("1: AudioInbox suchen")
        guard let root = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: Self.appGroup) else { throw WhisperEngineError.noSharedContainer }
        let inbox = root.appendingPathComponent("AudioInbox", isDirectory: true)
        let urls = (try? FileManager.default.contentsOfDirectory(at: inbox, includingPropertiesForKeys: [.contentModificationDateKey, .creationDateKey], options: [.skipsHiddenFiles])) ?? []
        let m4a = urls.filter { $0.pathExtension.lowercased() == "m4a" }
        guard !m4a.isEmpty else { throw WhisperEngineError.noAudio }
        return m4a.max { lhs, rhs in
            let lv = try? lhs.resourceValues(forKeys: [.contentModificationDateKey, .creationDateKey])
            let rv = try? rhs.resourceValues(forKeys: [.contentModificationDateKey, .creationDateKey])
            return (lv?.contentModificationDate ?? lv?.creationDate ?? .distantPast) < (rv?.contentModificationDate ?? rv?.creationDate ?? .distantPast)
        }!
    }

    func probeLatestAudio() throws -> AudioProbeResult {
        let source = try latestAudioURL()
        Self.setStage("2: M4A → 16 kHz Mono")
        let (samples, duration) = try decodeTo16kMonoFloat(source)
        Self.setStage("3: Audio-Konvertierung OK")
        return AudioProbeResult(sourceName: source.lastPathComponent, audioSeconds: duration, sampleCount: samples.count)
    }

    func probeModelLoad() throws -> ModelProbeResult {
        let model = try modelURL()
        Self.setStage("4: Base-Ladetest startet")
        var elapsed: Double = 0
        var errorPointer: UnsafeMutablePointer<CChar>?
        let rc: Int32 = model.path.withCString { modelPath in
            Int32(wm_whisper_test_model(modelPath, &elapsed, &errorPointer))
        }
        if let errorPointer {
            let message = String(cString: errorPointer)
            wm_whisper_free_string(errorPointer)
            throw WhisperEngineError.whisper(message)
        }
        guard rc == 0 else {
            throw WhisperEngineError.whisper("Base-Ladetest rc=\(rc)")
        }
        Self.setStage("5: Base laden/freigeben OK")
        return ModelProbeResult(loadSeconds: elapsed)
    }

    func transcribeLatest() throws -> WhisperRunResult { try transcribe(latestAudioURL()) }

    func transcribe(_ source: URL) throws -> WhisperRunResult {
        Self.setStage("2: M4A → 16 kHz Mono")
        let (samples, duration) = try decodeTo16kMonoFloat(source)
        guard !samples.isEmpty else { throw WhisperEngineError.audioConvert("0 Samples") }
        Self.setStage("3: Audio-Konvertierung OK")

        let model = try modelURL()

        // Preflight the exact heavy stages independently. If iOS kills the process,
        // the persisted stage identifies whether Mel or the encoder is responsible.
        Self.setStage("6A: Diagnose Context init")
        var preflightContextError: UnsafeMutablePointer<CChar>?
        let preflightContext = model.path.withCString { modelPath in
            wm_whisper_create_context(modelPath, &preflightContextError)
        }
        if let preflightContextError {
            let message = String(cString: preflightContextError)
            wm_whisper_free_string(preflightContextError)
            throw WhisperEngineError.whisper(message)
        }
        guard let preflightContext else { throw WhisperEngineError.whisper("Diagnose Context fehlt") }
        Self.setStage("6B: Diagnose Context OK")

        Self.setStage("6C: PCM → Mel starten")
        var melError: UnsafeMutablePointer<CChar>?
        let melRC: Int32 = samples.withUnsafeBufferPointer { buffer in
            Int32(wm_whisper_pcm_to_mel(preflightContext, buffer.baseAddress!, Int32(buffer.count), 1, &melError))
        }
        if let melError {
            let message = String(cString: melError)
            wm_whisper_free_string(melError)
            wm_whisper_free_context(preflightContext)
            throw WhisperEngineError.whisper(message)
        }
        guard melRC == 0 else {
            wm_whisper_free_context(preflightContext)
            throw WhisperEngineError.whisper("PCM→Mel rc=\(melRC)")
        }
        Self.setStage("6D: PCM → Mel OK")

        Self.setStage("6E: Encoder starten")
        var encoderError: UnsafeMutablePointer<CChar>?
        let encoderRC = Int32(wm_whisper_encode_only(preflightContext, 0, 1, &encoderError))
        if let encoderError {
            let message = String(cString: encoderError)
            wm_whisper_free_string(encoderError)
            wm_whisper_free_context(preflightContext)
            throw WhisperEngineError.whisper(message)
        }
        guard encoderRC == 0 else {
            wm_whisper_free_context(preflightContext)
            throw WhisperEngineError.whisper("Encoder rc=\(encoderRC)")
        }
        Self.setStage("6F: Encoder OK")
        wm_whisper_free_context(preflightContext)

        // Fresh context for the actual transcription. Build 6 uses one thread,
        // one greedy decoder and no temperature fallback to reduce A10 runtime pressure.
        Self.setStage("6G: Safe Context init")
        var contextError: UnsafeMutablePointer<CChar>?
        let context = model.path.withCString { modelPath in
            wm_whisper_create_context(modelPath, &contextError)
        }
        if let contextError {
            let message = String(cString: contextError)
            wm_whisper_free_string(contextError)
            throw WhisperEngineError.whisper(message)
        }
        guard let context else { throw WhisperEngineError.whisper("Safe Context fehlt") }
        Self.setStage("6H: Safe Context OK")
        defer { wm_whisper_free_context(context) }

        Self.setStage("6I: whisper_full Safe starten")
        var elapsed: Double = 0
        var runError: UnsafeMutablePointer<CChar>?
        let rc: Int32 = samples.withUnsafeBufferPointer { buffer in
            Int32(wm_whisper_run_full(context, buffer.baseAddress!, Int32(buffer.count), 1, &elapsed, &runError))
        }
        Self.setStage("6M: whisper_full zurück")
        if let runError {
            let message = String(cString: runError)
            wm_whisper_free_string(runError)
            throw WhisperEngineError.whisper(message)
        }
        guard rc == 0 else { throw WhisperEngineError.whisper("whisper_full rc=\(rc)") }

        Self.setStage("6N: Text aus Kontext lesen")
        var textError: UnsafeMutablePointer<CChar>?
        let resultPointer = wm_whisper_copy_text(context, &textError)
        if let textError {
            let message = String(cString: textError)
            wm_whisper_free_string(textError)
            throw WhisperEngineError.whisper(message)
        }
        guard let resultPointer else { throw WhisperEngineError.whisper("kein Ergebnis") }
        let text = String(cString: resultPointer).trimmingCharacters(in: .whitespacesAndNewlines)
        wm_whisper_free_string(resultPointer)
        Self.setStage("7: Whisper fertig")

        guard let root = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: Self.appGroup) else { throw WhisperEngineError.noSharedContainer }
        let outputDir = root.appendingPathComponent("WhisperText", isDirectory: true)
        try FileManager.default.createDirectory(at: outputDir, withIntermediateDirectories: true)
        let output = outputDir.appendingPathComponent(source.deletingPathExtension().lastPathComponent + ".txt")
        try (text + (text.isEmpty ? "" : "\n")).write(to: output, atomically: true, encoding: .utf8)
        Self.setStage("8: TXT gespeichert")
        return WhisperRunResult(sourceName: source.lastPathComponent, text: text, audioSeconds: duration, processingSeconds: elapsed, outputURL: output)
    }

    private func decodeTo16kMonoFloat(_ url: URL) throws -> ([Float], Double) {
        var fileRef: ExtAudioFileRef?
        var status = ExtAudioFileOpenURL(url as CFURL, &fileRef)
        guard status == noErr, let fileRef else { throw WhisperEngineError.audioOpen(osStatusDescription(status)) }
        defer { ExtAudioFileDispose(fileRef) }

        var clientFormat = AudioStreamBasicDescription(mSampleRate: Self.targetRate, mFormatID: kAudioFormatLinearPCM, mFormatFlags: kAudioFormatFlagsNativeFloatPacked, mBytesPerPacket: 4, mFramesPerPacket: 1, mBytesPerFrame: 4, mChannelsPerFrame: 1, mBitsPerChannel: 32, mReserved: 0)
        status = withUnsafePointer(to: &clientFormat) { ptr in
            ExtAudioFileSetProperty(fileRef, kExtAudioFileProperty_ClientDataFormat, UInt32(MemoryLayout<AudioStreamBasicDescription>.size), ptr)
        }
        guard status == noErr else { throw WhisperEngineError.audioConvert("ClientDataFormat: \(osStatusDescription(status))") }

        let chunkFrames: UInt32 = 16_000 * 2
        var chunk = [Float](repeating: 0, count: Int(chunkFrames))
        var samples: [Float] = []
        while true {
            var frames = chunkFrames
            status = chunk.withUnsafeMutableBytes { rawBuffer in
                var bufferList = AudioBufferList(mNumberBuffers: 1, mBuffers: AudioBuffer(mNumberChannels: 1, mDataByteSize: UInt32(rawBuffer.count), mData: rawBuffer.baseAddress))
                return ExtAudioFileRead(fileRef, &frames, &bufferList)
            }
            guard status == noErr else { throw WhisperEngineError.audioConvert("ExtAudioFileRead: \(osStatusDescription(status))") }
            if frames == 0 { break }
            samples.append(contentsOf: chunk.prefix(Int(frames)))
        }
        return (samples, Double(samples.count) / Self.targetRate)
    }

    private func osStatusDescription(_ status: OSStatus) -> String {
        if status == noErr { return "noErr" }
        let value = UInt32(bitPattern: status)
        let chars: [UInt8] = [UInt8((value >> 24) & 0xff), UInt8((value >> 16) & 0xff), UInt8((value >> 8) & 0xff), UInt8(value & 0xff)]
        if chars.allSatisfy({ $0 >= 32 && $0 <= 126 }), let fourCC = String(bytes: chars, encoding: .ascii) { return "OSStatus \(status) ('\(fourCC)')" }
        return "OSStatus \(status)"
    }
}
