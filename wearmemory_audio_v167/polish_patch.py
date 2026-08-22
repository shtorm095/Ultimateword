from pathlib import Path
import subprocess

root = Path('/tmp/wm167')
content = root/'WearMemory/ContentView.swift'
appmodel = root/'WearMemory/AppModel.swift'
audio = root/'WearMemory/AudioBufferManager.swift'
info = root/'WearMemory/Info.plist'

content.write_text(r'''import SwiftUI

struct ContentView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Text("WearMemory Audio")
                        .font(.system(size: 34, weight: .bold, design: .rounded))
                        .padding(.top, 10)

                    recordingCard

                    Text("Передача в Text")
                        .font(.title2.bold())
                    VStack(spacing: 10) {
                        infoRow("arrow.right.circle.fill", "После старта", "Открывается WearMemory Text", .blue)
                        infoRow("clock.fill", "Фрагмент", "3 минуты", .cyan)
                        infoRow("tray.and.arrow.down.fill", "Завершённые M4A", "локально → AudioInbox", .green)
                    }
                    .padding(14)
                    .cardStyle()

                    Text("Google Drive")
                        .font(.title2.bold())
                    driveCard

                    Text("Последние записи")
                        .font(.title2.bold())
                    recentAudioCard
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 28)
            }
        }
        .accentColor(.blue)
        .preferredColorScheme(.dark)
        .onAppear { model.requestPermissions() }
    }

    private var recordingCard: some View {
        VStack(spacing: 16) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Запись")
                        .font(.headline)
                    Text(model.audio.statusText)
                        .font(.caption)
                        .foregroundColor(model.audio.isRecording ? .green : .secondary)
                }
                Spacer()
                Circle()
                    .fill(model.audio.isRecording ? Color.red : Color.gray.opacity(0.5))
                    .frame(width: 14, height: 14)
            }

            Button {
                if model.audio.isRecording {
                    model.audio.stop()
                } else {
                    model.audio.start()
                }
            } label: {
                VStack(spacing: 12) {
                    ZStack {
                        Circle()
                            .fill(model.audio.isRecording ? Color.red : Color.blue)
                            .frame(width: 130, height: 130)
                            .shadow(color: (model.audio.isRecording ? Color.red : Color.blue).opacity(0.5), radius: 16)
                        Image(systemName: model.audio.isRecording ? "stop.fill" : "record.circle")
                            .font(.system(size: 44, weight: .bold))
                            .foregroundColor(.white)
                    }
                    Text(model.audio.isRecording ? "Остановить запись" : "Начать запись")
                        .font(.headline)
                        .foregroundColor(model.audio.isRecording ? .red : .blue)
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.plain)

            if model.audio.isRecording {
                Text("Запись продолжается в фоне. Для остановки вернитесь в WearMemory Audio.")
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .multilineTextAlignment(.center)
            }
        }
        .padding(16)
        .cardStyle()
    }

    private var driveCard: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Image(systemName: driveReady ? "checkmark.icloud.fill" : "icloud.slash.fill")
                    .font(.title2)
                    .foregroundColor(driveReady ? .green : .orange)
                VStack(alignment: .leading, spacing: 3) {
                    Text(driveReady ? "Подключено" : "Нужно подключение")
                        .font(.headline)
                    Text(model.driveSync.statusText)
                        .font(.caption)
                        .foregroundColor(driveReady ? .green : .orange)
                }
                Spacer()
            }
            .padding(14)

            Divider().background(Color.white.opacity(0.08))
            infoRow("doc.text.fill", "TXT", "Audio Lesen", .purple)
            Divider().background(Color.white.opacity(0.08))
            infoRow("music.note", "needs_pc", "Audio Hören", .green)

            Divider().background(Color.white.opacity(0.08))
            HStack(spacing: 10) {
                Button(driveReady ? "Переподключить" : "Подключить Google Drive") {
                    model.driveSync.connect()
                }
                .buttonStyle(.borderedProminent)

                if model.driveSync.isAuthorized {
                    Button("Отключить", role: .destructive) {
                        model.driveSync.disconnect()
                    }
                    .buttonStyle(.bordered)
                }
                Spacer()
            }
            .padding(14)

            if let error = model.driveSync.lastError {
                Divider().background(Color.white.opacity(0.08))
                Text(error)
                    .font(.caption)
                    .foregroundColor(.orange)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(14)
            }
        }
        .cardStyle()
    }

    private var recentAudioCard: some View {
        VStack(spacing: 0) {
            if model.audio.recentSegments.isEmpty {
                HStack {
                    Image(systemName: "waveform").foregroundColor(.blue)
                    Text("Пока нет завершённых записей").foregroundColor(.secondary)
                    Spacer()
                }
                .padding(14)
            } else {
                ForEach(Array(model.audio.recentSegments.prefix(6).enumerated()), id: \.element.id) { index, item in
                    if index > 0 { Divider().background(Color.white.opacity(0.08)) }
                    HStack(spacing: 10) {
                        Button {
                            model.audio.togglePlayback(item.url)
                        } label: {
                            Image(systemName: isPlaying(item.url) ? "stop.circle.fill" : "play.circle.fill")
                                .font(.title2)
                                .foregroundColor(.blue)
                        }
                        .buttonStyle(.plain)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(item.fileName)
                                .font(.subheadline.weight(.semibold))
                                .lineLimit(1)
                            Text("\(durationString(item.duration)) · \(ByteCountFormatter.string(fromByteCount: item.sizeBytes, countStyle: .file))")
                                .font(.caption2)
                                .foregroundColor(.secondary)
                        }
                        Spacer()
                    }
                    .padding(14)
                }
            }
        }
        .cardStyle()
    }

    private var driveReady: Bool {
        model.driveSync.isAuthorized && model.driveSync.foldersAuthorized
    }

    private func isPlaying(_ url: URL) -> Bool {
        model.audio.playingURL?.standardizedFileURL == url.standardizedFileURL
    }

    private func durationString(_ seconds: TimeInterval) -> String {
        guard seconds.isFinite, seconds > 0 else { return "--:--" }
        let total = Int(seconds.rounded())
        return String(format: "%02d:%02d", total / 60, total % 60)
    }

    private func infoRow(_ icon: String, _ title: String, _ value: String, _ tint: Color) -> some View {
        HStack(spacing: 10) {
            Image(systemName: icon).foregroundColor(tint).frame(width: 28)
            Text(title).foregroundColor(.white)
            Spacer()
            Text(value).foregroundColor(.secondary).multilineTextAlignment(.trailing)
        }
        .font(.subheadline)
        .padding(.horizontal, 13)
        .padding(.vertical, 5)
    }
}

private extension View {
    func cardStyle() -> some View {
        self
            .background(Color(white: 0.105))
            .cornerRadius(16)
            .overlay(RoundedRectangle(cornerRadius: 16).stroke(Color.white.opacity(0.035), lineWidth: 1))
    }
}
''')

s = audio.read_text()
needle = '    var onSegmentCompleted: ((URL, Date, Date) -> Void)?\n'
if needle not in s:
    raise SystemExit('Audio callback insertion point not found')
s = s.replace(needle, needle + '    var onManualRecordingStarted: (() -> Void)?\n', 1)
needle2 = '''                try self.configureSession()\n                try self.startNewSegment()\n'''
repl2 = '''                try self.configureSession()\n                try self.startNewSegment()\n                self.onManualRecordingStarted?()\n'''
if needle2 not in s:
    raise SystemExit('Audio manual start block not found')
s = s.replace(needle2, repl2, 1)
audio.write_text(s)

s = appmodel.read_text()
needle = '    private var cancellables = Set<AnyCancellable>()\n'
if needle not in s:
    raise SystemExit('AppModel property insertion point not found')
s = s.replace(needle, needle + '    private var lastCompletedAudioFile: String?\n    private var lastCompletedAt: Date?\n', 1)

old_sub = '''        audio.objectWillChange\n            .receive(on: DispatchQueue.main)\n            .sink { [weak self] _ in self?.objectWillChange.send() }\n            .store(in: &cancellables)\n'''
new_sub = '''        audio.objectWillChange\n            .receive(on: DispatchQueue.main)\n            .sink { [weak self] _ in\n                self?.objectWillChange.send()\n                DispatchQueue.main.async { self?.publishBridgeStatus() }\n            }\n            .store(in: &cancellables)\n'''
if old_sub not in s:
    raise SystemExit('Audio subscription block not found')
s = s.replace(old_sub, new_sub, 1)

old_cb = '''        audio.onSegmentCompleted = { [weak self] url, start, end in\n            self?.handoffAudioToText(url, startedAt: start, endedAt: end)\n        }\n        audio.onSegmentReady = nil\n'''
new_cb = '''        audio.onManualRecordingStarted = { [weak self] in\n            self?.publishBridgeStatus()\n            self?.openWearMemoryText()\n        }\n        audio.onSegmentCompleted = { [weak self] url, start, end in\n            self?.lastCompletedAudioFile = url.lastPathComponent\n            self?.lastCompletedAt = end\n            self?.handoffAudioToText(url, startedAt: start, endedAt: end)\n            self?.publishBridgeStatus()\n        }\n        audio.onSegmentReady = nil\n        DispatchQueue.main.async { [weak self] in self?.publishBridgeStatus() }\n'''
if old_cb not in s:
    raise SystemExit('Audio callback block not found')
s = s.replace(old_cb, new_cb, 1)

insert = '    private static let sharedGroupIdentifier = "group.local.pavel.WearMemory"\n\n'
if insert not in s:
    raise SystemExit('shared group marker not found')
helpers = r'''    private func openWearMemoryText() {
        guard let url = URL(string: "wearmemory-text://recording-started") else { return }
        DispatchQueue.main.async {
            UIApplication.shared.open(url, options: [:], completionHandler: nil)
        }
    }

    private func publishBridgeStatus() {
        let fm = FileManager.default
        guard let root = fm.containerURL(forSecurityApplicationGroupIdentifier: Self.sharedGroupIdentifier) else { return }
        let statusDir = root.appendingPathComponent("Status", isDirectory: true)
        do {
            try fm.createDirectory(at: statusDir, withIntermediateDirectories: true)
            let info = Bundle.main.infoDictionary ?? [:]
            let iso = ISO8601DateFormatter()
            var payload: [String: Any] = [
                "bridgeVersion": 2,
                "module": "audio",
                "appVersion": info["CFBundleShortVersionString"] as? String ?? "",
                "build": info["CFBundleVersion"] as? String ?? "",
                "isRecording": audio.isRecording,
                "audioStatus": audio.statusText,
                "driveStatus": driveSync.statusText,
                "drivePendingCount": driveSync.pendingCount,
                "updatedAt": iso.string(from: Date())
            ]
            if let file = lastCompletedAudioFile { payload["lastCompletedAudioFile"] = file }
            if let at = lastCompletedAt { payload["lastCompletedAt"] = iso.string(from: at) }
            if let err = driveSync.lastError { payload["driveLastError"] = err }
            let data = try JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys])
            try data.write(to: statusDir.appendingPathComponent("audio.json"), options: .atomic)
        } catch {
        }
    }

'''
s = s.replace(insert, insert + helpers, 1)
appmodel.write_text(s)

subprocess.run(['/usr/libexec/PlistBuddy','-c','Add :CFBundleURLTypes:1 dict',str(info)], check=False)
subprocess.run(['/usr/libexec/PlistBuddy','-c','Add :CFBundleURLTypes:1:CFBundleURLName string WearMemory Audio Integration',str(info)], check=False)
subprocess.run(['/usr/libexec/PlistBuddy','-c','Add :CFBundleURLTypes:1:CFBundleURLSchemes array',str(info)], check=False)
subprocess.run(['/usr/libexec/PlistBuddy','-c','Add :CFBundleURLTypes:1:CFBundleURLSchemes:0 string wearmemory-audio',str(info)], check=False)
subprocess.run(['/usr/libexec/PlistBuddy','-c','Set :CFBundleShortVersionString 1.6.7',str(info)], check=True)
subprocess.run(['/usr/libexec/PlistBuddy','-c','Set :CFBundleVersion 25',str(info)], check=True)
