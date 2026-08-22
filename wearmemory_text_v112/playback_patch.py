from pathlib import Path
import subprocess

root = Path('/tmp/wmtext112-src')
content = root/'WearMemoryText/ContentView.swift'
info = root/'WearMemoryText/Info.plist'

s = content.read_text()
s = s.replace('import Speech\n', 'import Speech\nimport AVFoundation\n', 1)
s = s.replace('''struct ContentView: View {\n    @EnvironmentObject var model: TextAppModel\n    @Environment(\\.openURL) private var openURL\n''','''struct ContentView: View {\n    @EnvironmentObject var model: TextAppModel\n    @Environment(\\.openURL) private var openURL\n    @StateObject private var audioPlayer = AudioInboxPlayer()\n''',1)
s = s.replace('''            home\n                .tabItem { Label("Главная", systemImage: "waveform.and.mic") }\n            texts\n                .tabItem { Label("Тексты", systemImage: "doc.text.fill") }\n''','''            home\n                .tabItem { Label("Главная", systemImage: "waveform.and.mic") }\n            audio\n                .tabItem { Label("Аудио", systemImage: "play.circle.fill") }\n            texts\n                .tabItem { Label("Тексты", systemImage: "doc.text.fill") }\n''',1)

marker = '''    private var texts: some View {\n'''
audio_view = r'''    private var audio: some View {
        screen {
            HStack {
                Text("Аудио")
                    .font(.system(size: 34, weight: .bold, design: .rounded))
                Spacer()
                Button {
                    audioPlayer.refresh()
                } label: {
                    Image(systemName: "arrow.clockwise")
                        .font(.title3.weight(.semibold))
                }
                .buttonStyle(.bordered)
                .accessibilityLabel("Обновить список аудио")
            }

            title("AudioInbox")
            VStack(spacing: 0) {
                if audioPlayer.files.isEmpty {
                    HStack(spacing: 10) {
                        Image(systemName: "music.note.list")
                            .foregroundColor(.blue)
                        Text("Пока нет M4A")
                            .foregroundColor(.secondary)
                        Spacer()
                    }
                    .padding(14)
                } else {
                    ForEach(Array(audioPlayer.files.enumerated()), id: \.element.id) { index, item in
                        if index > 0 { Divider().background(Color.white.opacity(0.08)) }
                        VStack(spacing: 8) {
                            HStack(spacing: 11) {
                                Button {
                                    audioPlayer.playPause(item.url)
                                } label: {
                                    Image(systemName: audioPlayer.isPlayingFile(item.url) ? "pause.circle.fill" : "play.circle.fill")
                                        .font(.system(size: 34))
                                        .foregroundColor(audioPlayer.isPlayingFile(item.url) ? .green : .blue)
                                }
                                .buttonStyle(.plain)
                                .accessibilityLabel(audioPlayer.isPlayingFile(item.url) ? "Пауза" : "Воспроизвести")

                                VStack(alignment: .leading, spacing: 3) {
                                    Text(item.url.lastPathComponent)
                                        .font(.subheadline.weight(.semibold))
                                        .foregroundColor(.white)
                                        .lineLimit(2)
                                    HStack(spacing: 8) {
                                        Text(item.durationText)
                                        Text(item.sizeText)
                                    }
                                    .font(.caption2)
                                    .foregroundColor(.secondary)
                                }
                                Spacer(minLength: 0)
                            }

                            if audioPlayer.isCurrentFile(item.url) {
                                HStack(spacing: 8) {
                                    Text(audioPlayer.currentTimeText)
                                        .font(.caption2.monospacedDigit())
                                        .foregroundColor(.secondary)
                                        .frame(width: 42, alignment: .leading)
                                    Slider(
                                        value: Binding(
                                            get: { audioPlayer.currentTime },
                                            set: { audioPlayer.seek(to: $0) }
                                        ),
                                        in: 0...max(audioPlayer.duration, 0.1)
                                    )
                                    Text(audioPlayer.durationText)
                                        .font(.caption2.monospacedDigit())
                                        .foregroundColor(.secondary)
                                        .frame(width: 42, alignment: .trailing)
                                }
                            }
                        }
                        .padding(14)
                    }
                }
            }
            .card()

            if let route = audioPlayer.outputRouteName {
                VStack(spacing: 0) {
                    info("headphones", "Аудиовыход", route, .cyan)
                }
                .padding(.vertical, 8)
                .card()
            }

            if let error = audioPlayer.lastError {
                Text(error)
                    .font(.caption)
                    .foregroundColor(.orange)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .onAppear { audioPlayer.refresh() }
    }

'''
if marker not in s:
    raise SystemExit('texts marker not found')
s = s.replace(marker, audio_view + marker, 1)

append = r'''

private struct AudioInboxFile: Identifiable {
    let id: String
    let url: URL
    let duration: TimeInterval
    let bytes: Int64

    var durationText: String { AudioInboxPlayer.formatTime(duration) }
    var sizeText: String { ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file) }
}

@MainActor
private final class AudioInboxPlayer: NSObject, ObservableObject, AVAudioPlayerDelegate {
    @Published var files: [AudioInboxFile] = []
    @Published var currentURL: URL?
    @Published var isPlaying = false
    @Published var currentTime: TimeInterval = 0
    @Published var duration: TimeInterval = 0
    @Published var lastError: String?
    @Published var outputRouteName: String?

    private let fm = FileManager.default
    private let groupIdentifier = "group.local.pavel.WearMemory"
    private var player: AVAudioPlayer?
    private var timer: Timer?

    deinit { timer?.invalidate() }

    func refresh() {
        lastError = nil
        outputRouteName = AVAudioSession.sharedInstance().currentRoute.outputs.first?.portName
        guard let root = fm.containerURL(forSecurityApplicationGroupIdentifier: groupIdentifier) else {
            files = []
            lastError = "Общая папка WearMemory недоступна"
            return
        }
        let inbox = root.appendingPathComponent("AudioInbox", isDirectory: true)
        do {
            try fm.createDirectory(at: inbox, withIntermediateDirectories: true)
            let urls = try fm.contentsOfDirectory(
                at: inbox,
                includingPropertiesForKeys: [.contentModificationDateKey, .fileSizeKey],
                options: [.skipsHiddenFiles]
            )
            let m4a = urls.filter { $0.pathExtension.lowercased() == "m4a" }
            files = m4a.map { url in
                let values = try? url.resourceValues(forKeys: [.fileSizeKey])
                let bytes = Int64(values?.fileSize ?? 0)
                let d = (try? AVAudioPlayer(contentsOf: url).duration) ?? 0
                return AudioInboxFile(id: url.path, url: url, duration: d, bytes: bytes)
            }.sorted { a, b in
                let ad = (try? a.url.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
                let bd = (try? b.url.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
                return ad > bd
            }
        } catch {
            files = []
            lastError = "Не удалось прочитать AudioInbox: \(error.localizedDescription)"
        }
    }

    func playPause(_ url: URL) {
        lastError = nil
        if currentURL == url, let player = player {
            if player.isPlaying {
                player.pause()
                isPlaying = false
                stopTimer()
            } else {
                do {
                    try configureAudioSession()
                    player.play()
                    isPlaying = true
                    startTimer()
                } catch {
                    lastError = "Аудиовыход: \(error.localizedDescription)"
                }
            }
            return
        }

        stopPlayback(resetSelection: false)
        do {
            try configureAudioSession()
            let newPlayer = try AVAudioPlayer(contentsOf: url)
            newPlayer.delegate = self
            newPlayer.prepareToPlay()
            player = newPlayer
            currentURL = url
            duration = newPlayer.duration
            currentTime = 0
            newPlayer.play()
            isPlaying = true
            outputRouteName = AVAudioSession.sharedInstance().currentRoute.outputs.first?.portName
            startTimer()
        } catch {
            stopPlayback(resetSelection: true)
            lastError = "Не удалось воспроизвести M4A: \(error.localizedDescription)"
        }
    }

    func seek(to value: TimeInterval) {
        guard let player = player else { return }
        let clamped = min(max(value, 0), player.duration)
        player.currentTime = clamped
        currentTime = clamped
    }

    func isCurrentFile(_ url: URL) -> Bool { currentURL == url }
    func isPlayingFile(_ url: URL) -> Bool { currentURL == url && isPlaying }

    var currentTimeText: String { Self.formatTime(currentTime) }
    var durationText: String { Self.formatTime(duration) }

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in
            self.currentTime = self.duration
            self.isPlaying = false
            self.stopTimer()
        }
    }

    private func configureAudioSession() throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playback, mode: .default, options: [])
        try session.setActive(true)
        outputRouteName = session.currentRoute.outputs.first?.portName
    }

    private func startTimer() {
        stopTimer()
        timer = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self = self, let player = self.player else { return }
                self.currentTime = player.currentTime
                self.duration = player.duration
                self.isPlaying = player.isPlaying
                self.outputRouteName = AVAudioSession.sharedInstance().currentRoute.outputs.first?.portName
            }
        }
    }

    private func stopTimer() {
        timer?.invalidate()
        timer = nil
    }

    private func stopPlayback(resetSelection: Bool) {
        player?.stop()
        player = nil
        stopTimer()
        isPlaying = false
        currentTime = 0
        duration = 0
        if resetSelection { currentURL = nil }
    }

    static func formatTime(_ value: TimeInterval) -> String {
        guard value.isFinite, value >= 0 else { return "0:00" }
        let total = Int(value.rounded(.down))
        return String(format: "%d:%02d", total / 60, total % 60)
    }
}
'''
s += append
content.write_text(s)

subprocess.run(['/usr/libexec/PlistBuddy','-c','Set :CFBundleShortVersionString 1.1.2',str(info)], check=True)
subprocess.run(['/usr/libexec/PlistBuddy','-c','Set :CFBundleVersion 12',str(info)], check=True)
