import Foundation
import AVFoundation

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
        // Idempotent local result: same M4A always overwrites the same TXT, never creates duplicates.
        try (text + (text.isEmpty ? "" : "\n")).write(to: output, atomically: true, encoding: .utf8)

        return WhisperRunResult(
            sourceName: source.lastPathComponent,
            text: text,
            audioSeconds: duration,
            processingSeconds: elapsed,
            outputURL: output
        )
    }

    private func decodeTo16kMonoFloat(_ url: URL) throws -> ([Float], Double) {
        let file: AVAudioFile
        do { file = try AVAudioFile(forReading: url) }
        catch { throw WhisperEngineError.audioOpen(error.localizedDescription) }

        guard let outputFormat = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: Self.targetRate,
            channels: 1,
            interleaved: false
        ) else { throw WhisperEngineError.audioConvert("Zielformat 16 kHz mono nicht verfügbar") }

        let inputFormat = file.processingFormat
        guard let converter = AVAudioConverter(from: inputFormat, to: outputFormat) else {
            throw WhisperEngineError.audioConvert("AVAudioConverter konnte nicht erstellt werden")
        }

        let outputCapacity: AVAudioFrameCount = 16_000 * 10
        var result: [Float] = []
        var reachedEOF = false
        var conversionError: Error?

        while !reachedEOF {
            guard let outBuffer = AVAudioPCMBuffer(pcmFormat: outputFormat, frameCapacity: outputCapacity) else {
                throw WhisperEngineError.audioConvert("Ausgabepuffer konnte nicht erstellt werden")
            }

            var localError: NSError?
            let status = converter.convert(to: outBuffer, error: &localError) { packetCount, outStatus in
                let inputCapacity = max(1024, packetCount)
                guard let inBuffer = AVAudioPCMBuffer(pcmFormat: inputFormat, frameCapacity: inputCapacity) else {
                    outStatus.pointee = .noDataNow
                    return nil
                }
                do {
                    try file.read(into: inBuffer, frameCount: inputCapacity)
                    if inBuffer.frameLength == 0 {
                        reachedEOF = true
                        outStatus.pointee = .endOfStream
                        return nil
                    }
                    outStatus.pointee = .haveData
                    return inBuffer
                } catch {
                    conversionError = error
                    reachedEOF = true
                    outStatus.pointee = .endOfStream
                    return nil
                }
            }

            if let localError { throw WhisperEngineError.audioConvert(localError.localizedDescription) }
            if let conversionError { throw WhisperEngineError.audioConvert(conversionError.localizedDescription) }

            if outBuffer.frameLength > 0, let channel = outBuffer.floatChannelData?[0] {
                result.append(contentsOf: UnsafeBufferPointer(start: channel, count: Int(outBuffer.frameLength)))
            }
            if status == .error { throw WhisperEngineError.audioConvert("AVAudioConverter Status error") }
            if status == .endOfStream { reachedEOF = true }
        }

        let duration = Double(result.count) / Self.targetRate
        return (result, duration)
    }
}
