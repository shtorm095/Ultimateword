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

enum WhisperEngineError: LocalizedError {
    case noSharedContainer
    case noAudio
    case modelMissing
    case audioOpen(String)
    case audioConvert(String)
    case whisper(String)

    var errorDescription: String? {
        switch self {
        case .noSharedContainer: return "Gemeinsamer WearMemory-Speicher ist nicht verfügbar."
        case .noAudio: return "Kein M4A in AudioInbox gefunden."
        case .modelMissing: return "Whisper Base Modell fehlt."
        case .audioOpen(let value): return "M4A konnte nicht geöffnet werden: \(value)"
        case .audioConvert(let value): return "Audio-Konvertierung fehlgeschlagen: \(value)"
        case .whisper(let value): return "Whisper: \(value)"
        }
    }
}

final class WhisperEngine {
    static let appGroup = "group.local.pavel.WearMemory"
    // whisper.cpp expects PCM at WHISPER_SAMPLE_RATE = 16000 Hz.
    static let targetRate: Double = 16_000

    func latestAudioURL() throws -> URL {
        guard let root = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: Self.appGroup) else {
            throw WhisperEngineError.noSharedContainer
        }
        let inbox = root.appendingPathComponent("AudioInbox", isDirectory: true)
        let urls = (try? FileManager.default.contentsOfDirectory(
            at: inbox,
            includingPropertiesForKeys: [.contentModificationDateKey, .creationDateKey],
            options: [.skipsHiddenFiles]
        )) ?? []
        let m4a = urls.filter { $0.pathExtension.lowercased() == "m4a" }
        guard !m4a.isEmpty else { throw WhisperEngineError.noAudio }
        return m4a.max { lhs, rhs in
            let lv = try? lhs.resourceValues(forKeys: [.contentModificationDateKey, .creationDateKey])
            let rv = try? rhs.resourceValues(forKeys: [.contentModificationDateKey, .creationDateKey])
            let ld = lv?.contentModificationDate ?? lv?.creationDate ?? .distantPast
            let rd = rv?.contentModificationDate ?? rv?.creationDate ?? .distantPast
            return ld < rd
        }!
    }

    func transcribeLatest() throws -> WhisperRunResult {
        let source = try latestAudioURL()
        return try transcribe(source)
    }

    func transcribe(_ source: URL) throws -> WhisperRunResult {
        guard let model = Bundle.main.url(forResource: "ggml-base", withExtension: "bin") else {
            throw WhisperEngineError.modelMissing
        }

        let (samples, duration) = try decodeTo16kMonoFloat(source)
        guard !samples.isEmpty else { throw WhisperEngineError.audioConvert("0 Samples") }

        var elapsed: Double = 0
        var errorPointer: UnsafeMutablePointer<CChar>?
        let resultPointer: UnsafePointer<CChar>? = model.path.withCString { modelPath in
            samples.withUnsafeBufferPointer { buffer in
                wm_whisper_transcribe(modelPath, buffer.baseAddress!, Int32(buffer.count), 2, &elapsed, &errorPointer)
            }
        }
        if let errorPointer {
            let message = String(cString: errorPointer)
            wm_whisper_free_string(errorPointer)
            throw WhisperEngineError.whisper(message)
        }
        guard let resultPointer else { throw WhisperEngineError.whisper("kein Ergebnis") }
        let text = String(cString: resultPointer).trimmingCharacters(in: .whitespacesAndNewlines)
        wm_whisper_free_string(resultPointer)

        guard let root = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: Self.appGroup) else {
            throw WhisperEngineError.noSharedContainer
        }
        let outputDir = root.appendingPathComponent("WhisperText", isDirectory: true)
        try FileManager.default.createDirectory(at: outputDir, withIntermediateDirectories: true)
        let output = outputDir.appendingPathComponent(source.deletingPathExtension().lastPathComponent + ".txt")
        try (text + (text.isEmpty ? "" : "\n")).write(to: output, atomically: true, encoding: .utf8)

        return WhisperRunResult(
            sourceName: source.lastPathComponent,
            text: text,
            audioSeconds: duration,
            processingSeconds: elapsed,
            outputURL: output
        )
    }

    // iOS 15 build 2: use ExtAudioFile instead of AVAudioConverter's pull callback.
    // ExtAudioFile lets AudioToolbox decode AAC/M4A and resample directly to the exact
    // PCM format whisper.cpp requires: Float32, mono, 16 kHz.
    private func decodeTo16kMonoFloat(_ url: URL) throws -> ([Float], Double) {
        var fileRef: ExtAudioFileRef?
        var status = ExtAudioFileOpenURL(url as CFURL, &fileRef)
        guard status == noErr, let fileRef else {
            throw WhisperEngineError.audioOpen(osStatusDescription(status))
        }
        defer { ExtAudioFileDispose(fileRef) }

        var clientFormat = AudioStreamBasicDescription(
            mSampleRate: Self.targetRate,
            mFormatID: kAudioFormatLinearPCM,
            mFormatFlags: kAudioFormatFlagsNativeFloatPacked,
            mBytesPerPacket: UInt32(MemoryLayout<Float>.size),
            mFramesPerPacket: 1,
            mBytesPerFrame: UInt32(MemoryLayout<Float>.size),
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
            throw WhisperEngineError.audioConvert("ClientDataFormat: \(osStatusDescription(status))")
        }

        let chunkFrames: UInt32 = 16_000 * 5
        var chunk = [Float](repeating: 0, count: Int(chunkFrames))
        var samples: [Float] = []
        samples.reserveCapacity(Int(Self.targetRate * 180))

        while true {
            var frames = chunkFrames
            status = chunk.withUnsafeMutableBytes { rawBuffer in
                var audioBuffer = AudioBuffer(
                    mNumberChannels: 1,
                    mDataByteSize: UInt32(rawBuffer.count),
                    mData: rawBuffer.baseAddress
                )
                var bufferList = AudioBufferList(mNumberBuffers: 1, mBuffers: audioBuffer)
                return ExtAudioFileRead(fileRef, &frames, &bufferList)
            }

            guard status == noErr else {
                throw WhisperEngineError.audioConvert("ExtAudioFileRead: \(osStatusDescription(status))")
            }
            if frames == 0 { break }
            samples.append(contentsOf: chunk.prefix(Int(frames)))
        }

        return (samples, Double(samples.count) / Self.targetRate)
    }

    private func osStatusDescription(_ status: OSStatus) -> String {
        if status == noErr { return "noErr" }

        let value = UInt32(bitPattern: status)
        let chars: [UInt8] = [
            UInt8((value >> 24) & 0xff),
            UInt8((value >> 16) & 0xff),
            UInt8((value >> 8) & 0xff),
            UInt8(value & 0xff)
        ]
        let printable = chars.allSatisfy { $0 >= 32 && $0 <= 126 }
        if printable, let fourCC = String(bytes: chars, encoding: .ascii) {
            return "OSStatus \(status) ('\(fourCC)')"
        }
        return "OSStatus \(status)"
    }
}
