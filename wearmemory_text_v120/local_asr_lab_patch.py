from pathlib import Path

root = Path('/tmp/wmtext120-src')
app = root/'WearMemoryText'
content = app/'ContentView.swift'
info = app/'Info.plist'
project = root/'project.yml'
lab = app/'LocalASRLab.swift'

if not content.exists():
    raise SystemExit('ContentView.swift not found')

lab.write_text(r'''import Foundation
import SwiftUI
import AVFoundation
import whisper
import VoskC

final class LocalASRLab: ObservableObject {
    @Published private(set) var files: [URL] = []
    @Published var selectedURL: URL?
    @Published private(set) var statusText = "Готов к тесту"
    @Published private(set) var isRunning = false
    @Published private(set) var voskText = ""
    @Published private(set) var whisperText = ""
    @Published private(set) var voskSeconds: Double?
    @Published private(set) var whisperSeconds: Double?
    @Published private(set) var lastError: String?

    private let fm = FileManager.default
    private let queue = DispatchQueue(label: "WearMemoryText.LocalASR", qos: .userInitiated)
    private let appGroupID = "group.local.pavel.WearMemory"

    func refresh() {
        do {
            guard let root = fm.containerURL(forSecurityApplicationGroupIdentifier: appGroupID) else {
                throw LabError.message("App Group недоступен")
            }
            let inbox = root.appendingPathComponent("AudioInbox", isDirectory: true)
            let urls = try fm.contentsOfDirectory(
                at: inbox,
                includingPropertiesForKeys: [.contentModificationDateKey, .fileSizeKey],
                options: [.skipsHiddenFiles]
            ).filter { $0.pathExtension.lowercased() == "m4a" }
            .sorted {
                let ld = (try? $0.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
                let rd = (try? $1.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
                return ld > rd
            }
            DispatchQueue.main.async {
                self.files = urls
                if self.selectedURL == nil || !urls.contains(where: { $0 == self.selectedURL }) {
                    self.selectedURL = urls.first
                }
                self.lastError = nil
            }
        } catch {
            DispatchQueue.main.async { self.lastError = error.localizedDescription }
        }
    }

    func runComparison() {
        guard !isRunning, let url = selectedURL else { return }
        isRunning = true
        voskText = ""
        whisperText = ""
        voskSeconds = nil
        whisperSeconds = nil
        lastError = nil
        statusText = "Подготавливаю 16 kHz mono…"

        queue.async { [weak self] in
            guard let self = self else { return }
            do {
                let pcm = try Self.decode16kMono(url: url)

                DispatchQueue.main.async { self.statusText = "Vosk German small…" }
                let v0 = CFAbsoluteTimeGetCurrent()
                let vText = try Self.transcribeVosk(pcm16: pcm)
                let vTime = CFAbsoluteTimeGetCurrent() - v0
                DispatchQueue.main.async {
                    self.voskText = vText
                    self.voskSeconds = vTime
                    self.statusText = "Whisper base · Deutsch…"
                }

                let w0 = CFAbsoluteTimeGetCurrent()
                let wText = try Self.transcribeWhisper(pcm16: pcm)
                let wTime = CFAbsoluteTimeGetCurrent() - w0

                DispatchQueue.main.async {
                    self.whisperText = wText
                    self.whisperSeconds = wTime
                    self.statusText = "Сравнение завершено"
                    self.isRunning = false
                }
            } catch {
                DispatchQueue.main.async {
                    self.lastError = error.localizedDescription
                    self.statusText = "Ошибка"
                    self.isRunning = false
                }
            }
        }
    }

    private static var modelRoot: URL {
        Bundle.main.bundleURL.appendingPathComponent("LocalASRModels", isDirectory: true)
    }

    private static func transcribeVosk(pcm16: Data) throws -> String {
        let modelURL = modelRoot.appendingPathComponent("vosk-model-small-de-0.15", isDirectory: true)
        guard FileManager.default.fileExists(atPath: modelURL.path) else {
            throw LabError.message("Не найдена модель Vosk German")
        }

        let model: OpaquePointer? = modelURL.path.withCString { vosk_model_new($0) }
        guard let model = model else { throw LabError.message("Vosk не смог загрузить немецкую модель") }
        defer { vosk_model_free(model) }

        guard let recognizer = vosk_recognizer_new(model, 16_000) else {
            throw LabError.message("Vosk не смог создать recognizer")
        }
        defer { vosk_recognizer_free(recognizer) }

        vosk_recognizer_set_words(recognizer, 1)
        let chunkBytes = 16_384
        var offset = 0
        while offset < pcm16.count {
            let count = min(chunkBytes, pcm16.count - offset)
            pcm16.withUnsafeBytes { raw in
                guard let base = raw.baseAddress else { return }
                let ptr = base.advanced(by: offset).assumingMemoryBound(to: Int8.self)
                _ = vosk_recognizer_accept_waveform(recognizer, ptr, Int32(count))
            }
            offset += count
        }
        guard let resultC = vosk_recognizer_final_result(recognizer) else {
            throw LabError.message("Vosk не вернул результат")
        }
        let json = String(cString: resultC)
        guard let data = json.data(using: .utf8),
              let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw LabError.message("Не удалось разобрать результат Vosk")
        }
        return (object["text"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func transcribeWhisper(pcm16: Data) throws -> String {
        let modelURL = modelRoot.appendingPathComponent("ggml-base.bin")
        guard FileManager.default.fileExists(atPath: modelURL.path) else {
            throw LabError.message("Не найдена модель Whisper base")
        }

        var contextParams = whisper_context_default_params()
        // A10 / iOS 15: CPU path first for maximum compatibility and predictable memory use.
        contextParams.use_gpu = false
        contextParams.flash_attn = false

        let context: OpaquePointer? = modelURL.path.withCString {
            whisper_init_from_file_with_params($0, contextParams)
        }
        guard let context = context else { throw LabError.message("Whisper не смог загрузить base model") }
        defer { whisper_free(context) }

        var samples = [Float]()
        samples.reserveCapacity(pcm16.count / 2)
        pcm16.withUnsafeBytes { raw in
            let values = raw.bindMemory(to: Int16.self)
            for value in values {
                samples.append(Float(Int16(littleEndian: value)) / 32768.0)
            }
        }

        var params = whisper_full_default_params(WHISPER_SAMPLING_GREEDY)
        params.print_realtime = false
        params.print_progress = false
        params.print_timestamps = false
        params.print_special = false
        params.translate = false
        params.n_threads = 2
        params.offset_ms = 0
        params.no_context = true
        params.single_segment = false

        let rc: Int32 = "de".withCString { de in
            params.language = de
            return samples.withUnsafeBufferPointer { buffer in
                whisper_full(context, params, buffer.baseAddress, Int32(buffer.count))
            }
        }
        guard rc == 0 else { throw LabError.message("Whisper завершился с кодом \(rc)") }

        var text = ""
        let n = whisper_full_n_segments(context)
        if n > 0 {
            for i in 0..<n {
                if let c = whisper_full_get_segment_text(context, i) {
                    text += String(cString: c)
                }
            }
        }
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func decode16kMono(url: URL) throws -> Data {
        let asset = AVURLAsset(url: url)
        guard let track = asset.tracks(withMediaType: .audio).first else {
            throw LabError.message("В M4A нет аудиодорожки")
        }
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: 16_000,
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
            AVLinearPCMIsBigEndianKey: false,
            AVLinearPCMIsNonInterleaved: false
        ]
        let output = AVAssetReaderTrackOutput(track: track, outputSettings: settings)
        output.alwaysCopiesSampleData = false
        let reader = try AVAssetReader(asset: asset)
        guard reader.canAdd(output) else { throw LabError.message("Невозможно декодировать M4A в PCM") }
        reader.add(output)
        guard reader.startReading() else {
            throw reader.error ?? LabError.message("Не удалось начать чтение M4A")
        }

        var data = Data()
        while let sample = output.copyNextSampleBuffer() {
            autoreleasepool {
                if let block = CMSampleBufferGetDataBuffer(sample) {
                    let length = CMBlockBufferGetDataLength(block)
                    var chunk = Data(count: length)
                    chunk.withUnsafeMutableBytes { dst in
                        if let base = dst.baseAddress {
                            _ = CMBlockBufferCopyDataBytes(block, atOffset: 0, dataLength: length, destination: base)
                        }
                    }
                    data.append(chunk)
                }
            }
        }
        guard reader.status == .completed else {
            throw reader.error ?? LabError.message("Декодирование M4A не завершено")
        }
        guard !data.isEmpty else { throw LabError.message("PCM после декодирования пуст") }
        return data
    }

    private enum LabError: LocalizedError {
        case message(String)
        var errorDescription: String? {
            switch self { case .message(let value): return value }
        }
    }
}

struct LocalASRLabView: View {
    @ObservedObject var lab: LocalASRLab

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack {
                        Text("Local ASR")
                            .font(.system(size: 34, weight: .bold, design: .rounded))
                        Spacer()
                        Button { lab.refresh() } label: { Image(systemName: "arrow.clockwise") }
                            .buttonStyle(.bordered)
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        Text("Один M4A → два локальных распознавания")
                            .font(.headline)
                        Picker("Аудиофайл", selection: Binding(
                            get: { lab.selectedURL },
                            set: { lab.selectedURL = $0 }
                        )) {
                            ForEach(lab.files, id: \.path) { url in
                                Text(url.lastPathComponent).tag(Optional(url))
                            }
                        }
                        .pickerStyle(.menu)

                        Text("Vosk: German small 0.15 · Whisper: base, language=de · обработка последовательно")
                            .font(.caption)
                            .foregroundColor(.secondary)

                        Button {
                            lab.runComparison()
                        } label: {
                            Label(lab.isRunning ? "Распознаю…" : "Сравнить Vosk и Whisper", systemImage: "waveform.badge.magnifyingglass")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(lab.isRunning || lab.selectedURL == nil)

                        Text(lab.statusText)
                            .font(.caption)
                            .foregroundColor(lab.lastError == nil ? .green : .orange)
                        if let error = lab.lastError {
                            Text(error).font(.caption).foregroundColor(.orange)
                        }
                    }
                    .padding(14)
                    .background(Color.white.opacity(0.06))
                    .clipShape(RoundedRectangle(cornerRadius: 16))

                    resultCard(title: "Vosk German small", text: lab.voskText, seconds: lab.voskSeconds)
                    resultCard(title: "Whisper base (Deutsch)", text: lab.whisperText, seconds: lab.whisperSeconds)
                }
                .padding(16)
            }
        }
        .onAppear { lab.refresh() }
    }

    private func resultCard(title: String, text: String, seconds: Double?) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(title).font(.headline)
                Spacer()
                if let seconds = seconds {
                    Text(String(format: "%.1f s", seconds))
                        .font(.caption.monospacedDigit())
                        .foregroundColor(.cyan)
                }
            }
            Text(text.isEmpty ? "Результата пока нет" : text)
                .foregroundColor(text.isEmpty ? .secondary : .white)
                .textSelection(.enabled)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(Color.white.opacity(0.06))
        .clipShape(RoundedRectangle(cornerRadius: 16))
    }
}
''')

c = content.read_text()
old = '    @StateObject private var audioPlayer = AudioInboxPlayer()\n'
new = old + '    @StateObject private var localASR = LocalASRLab()\n'
if old not in c: raise SystemExit('audioPlayer state not found')
c = c.replace(old, new, 1)
old = '''            texts\n                .tabItem { Label("Тексты", systemImage: "doc.text.fill") }\n'''
new = old + '''            LocalASRLabView(lab: localASR)\n                .tabItem { Label("Local ASR", systemImage: "cpu") }\n'''
if old not in c: raise SystemExit('texts tab not found')
c = c.replace(old, new, 1)
content.write_text(c)

p = project.read_text()
needle = "        IPHONEOS_DEPLOYMENT_TARGET: '15.0'\n"
replacement = needle + "        SWIFT_INCLUDE_PATHS: /tmp/wmtext120-native/modules\n        LIBRARY_SEARCH_PATHS: /tmp/wmtext120-native/lib\n        OTHER_LDFLAGS: '$(inherited) -lwhisper_all -lvosk_arm64 -lc++ -framework Accelerate'\n        DEAD_CODE_STRIPPING: YES\n"
if needle not in p: raise SystemExit('deployment setting not found')
p = p.replace(needle, replacement, 1)
project.write_text(p)

s = info.read_text()
s = s.replace('<string>1.1.9</string>', '<string>1.2.0</string>', 1)
s = s.replace('<string>19</string>', '<string>20</string>', 1)
if '<string>1.2.0</string>' not in s or '<string>20</string>' not in s:
    raise SystemExit('version bump failed')
info.write_text(s)

print('patched v1.2.0 local ASR lab')
