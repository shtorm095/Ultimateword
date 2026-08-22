from pathlib import Path
import subprocess

root = Path('/tmp/wm168')
audio = root/'WearMemory/AudioBufferManager.swift'
content = root/'WearMemory/ContentView.swift'
model = root/'WearMemory/AppModel.swift'
app = root/'WearMemory/WearMemoryApp.swift'
info = root/'WearMemory/Info.plist'

s = audio.read_text()
s = s.replace('@Published private(set) var inputName = "—"\n', '@Published private(set) var inputName = "—"\n    @Published private(set) var outputName = "—"\n    @Published private(set) var availableInputs: [AudioInputChoice] = []\n    @Published private(set) var selectedInputUID: String? = UserDefaults.standard.string(forKey: "wearmemory.audio.preferredInputUID")\n', 1)
s = s.replace('''        pruneBuffer()\n        refreshStats()\n\n        interruptionObserver''','''        pruneBuffer()\n        refreshStats()\n        refreshAudioRoutes()\n\n        interruptionObserver''',1)
s = s.replace('''        ) { [weak self] _ in self?.updateInputName() }\n''','''        ) { [weak self] _ in self?.refreshAudioRoutes() }\n''',1)
s = s.replace('''                try session.setCategory(.playback, mode: .default, options: [])\n''','''                try session.setCategory(.playback, mode: .default, options: [.mixWithOthers])\n''',1)

old = '''    private func configureSession() throws {\n        let session = AVAudioSession.sharedInstance()\n        try session.setCategory(.playAndRecord, mode: .default, options: [.allowBluetooth])\n        try session.setActive(true, options: [])\n        updateInputName()\n    }\n'''
new = r'''    func refreshAudioRoutes() {
        let session = AVAudioSession.sharedInstance()
        let shouldDeactivate = !isRecording && player == nil
        do {
            if shouldDeactivate {
                try session.setCategory(.playAndRecord, mode: .default, options: [.allowBluetooth, .allowBluetoothA2DP, .mixWithOthers])
                try session.setActive(true, options: [])
            }
            publishRouteChoices(session)
            if shouldDeactivate {
                try? session.setActive(false, options: [.notifyOthersOnDeactivation])
            }
        } catch {
            publishRouteChoices(session)
        }
    }

    func selectInput(uid: String?) {
        let session = AVAudioSession.sharedInstance()
        let shouldDeactivate = !isRecording && player == nil
        do {
            if shouldDeactivate {
                try session.setCategory(.playAndRecord, mode: .default, options: [.allowBluetooth, .allowBluetoothA2DP, .mixWithOthers])
                try session.setActive(true, options: [])
            }
            let port = uid.flatMap { wanted in session.availableInputs?.first(where: { $0.uid == wanted }) }
            try session.setPreferredInput(port)
            selectedInputUID = port?.uid
            if let value = selectedInputUID {
                UserDefaults.standard.set(value, forKey: "wearmemory.audio.preferredInputUID")
            } else {
                UserDefaults.standard.removeObject(forKey: "wearmemory.audio.preferredInputUID")
            }
            publishRouteChoices(session)
            if shouldDeactivate {
                try? session.setActive(false, options: [.notifyOthersOnDeactivation])
            }
        } catch {
            statusText = "Аудиовход: \(error.localizedDescription)"
        }
    }

    private func configureSession() throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .default, options: [.allowBluetooth, .allowBluetoothA2DP, .mixWithOthers])
        try session.setActive(true, options: [])
        if let uid = selectedInputUID,
           let port = session.availableInputs?.first(where: { $0.uid == uid }) {
            try? session.setPreferredInput(port)
        }
        publishRouteChoices(session)
    }

    private func publishRouteChoices(_ session: AVAudioSession) {
        let inputs = (session.availableInputs ?? []).map {
            AudioInputChoice(uid: $0.uid, name: $0.portName, type: $0.portType.rawValue)
        }
        let currentInput = session.currentRoute.inputs.first?.portName ?? session.preferredInput?.portName ?? "Встроенный микрофон"
        let currentOutput = session.currentRoute.outputs.first?.portName ?? "Системный аудиовыход"
        DispatchQueue.main.async {
            self.availableInputs = inputs
            self.inputName = currentInput
            self.outputName = currentOutput
        }
    }
'''
if old not in s:
    raise SystemExit('configureSession block not found')
s = s.replace(old, new, 1)

old2 = '''    private func updateInputName() {\n        let route = AVAudioSession.sharedInstance().currentRoute\n        DispatchQueue.main.async {\n            self.inputName = route.inputs.first?.portName ?? "Встроенный микрофон"\n        }\n    }\n'''
s = s.replace(old2, '', 1)

s += r'''

struct AudioInputChoice: Identifiable, Equatable {
    let uid: String
    let name: String
    let type: String
    var id: String { uid }
}
'''
audio.write_text(s)

content.write_text(r'''import SwiftUI
import AVKit

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

                    Text("Аудиоустройства")
                        .font(.title2.bold())
                    audioDevicesCard

                    Text("Передача в Text")
                        .font(.title2.bold())
                    VStack(spacing: 10) {
                        infoRow("arrow.right.circle.fill", "После старта", "Открывается WearMemory Text", .blue)
                        infoRow("clock.fill", "Фрагмент", "3 минуты", .cyan)
                        infoRow("tray.and.arrow.down.fill", "Завершённые M4A", "локально → AudioInbox", .green)
                    }
                    .padding(14)
                    .cardStyle()

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
        .onAppear {
            model.requestPermissions()
            model.audio.refreshAudioRoutes()
        }
    }

    private var recordingCard: some View {
        VStack(spacing: 16) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Запись").font(.headline)
                    Text(model.audio.statusText)
                        .font(.caption)
                        .foregroundColor(model.audio.isRecording ? .green : .secondary)
                }
                Spacer()
                Circle()
                    .fill(model.audio.isRecording ? Color.red : Color.blue)
                    .frame(width: 14, height: 14)
            }

            Button {
                model.audio.isRecording ? model.audio.stop() : model.audio.start()
            } label: {
                VStack(spacing: 12) {
                    ZStack {
                        Circle()
                            .fill(model.audio.isRecording ? Color.red : Color.blue)
                            .frame(width: 130, height: 130)
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
        }
        .padding(16)
        .cardStyle()
    }

    private var audioDevicesCard: some View {
        VStack(spacing: 0) {
            infoRow("mic.fill", "Сейчас записывает", model.audio.inputName, .green)
            Divider().background(Color.white.opacity(0.08))
            HStack(spacing: 10) {
                Image(systemName: "slider.horizontal.3").foregroundColor(.blue).frame(width: 28)
                Text("Источник записи")
                Spacer()
                Menu {
                    Button("Автоматически") { model.audio.selectInput(uid: nil) }
                    ForEach(model.audio.availableInputs) { item in
                        Button(item.name) { model.audio.selectInput(uid: item.uid) }
                    }
                } label: {
                    Text(selectedInputLabel)
                        .foregroundColor(.blue)
                        .multilineTextAlignment(.trailing)
                }
            }
            .font(.subheadline)
            .padding(13)

            Divider().background(Color.white.opacity(0.08))
            infoRow("headphones", "Аудиовыход", model.audio.outputName, .cyan)
            Divider().background(Color.white.opacity(0.08))
            HStack {
                Text("Внешний аудиовыход")
                Spacer()
                SystemAudioRoutePicker()
                    .frame(width: 48, height: 44)
            }
            .padding(.horizontal, 13)
            .padding(.vertical, 4)
        }
        .cardStyle()
    }

    private var selectedInputLabel: String {
        guard let uid = model.audio.selectedInputUID,
              let item = model.audio.availableInputs.first(where: { $0.uid == uid }) else { return "Авто" }
        return item.name
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
                        Button { model.audio.togglePlayback(item.url) } label: {
                            Image(systemName: model.audio.isPlaying(item.url) ? "stop.circle.fill" : "play.circle.fill")
                                .font(.title2).foregroundColor(.blue)
                        }
                        .buttonStyle(.plain)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(item.fileName).font(.subheadline.weight(.semibold)).lineLimit(1)
                            Text("\(durationString(item.duration)) · \(ByteCountFormatter.string(fromByteCount: item.sizeBytes, countStyle: .file))")
                                .font(.caption2).foregroundColor(.secondary)
                        }
                        Spacer()
                    }
                    .padding(14)
                }
            }
        }
        .cardStyle()
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
            Text(value).foregroundColor(.secondary).multilineTextAlignment(.trailing).lineLimit(2)
        }
        .font(.subheadline)
        .padding(.horizontal, 13)
        .padding(.vertical, 5)
    }
}

private struct SystemAudioRoutePicker: UIViewRepresentable {
    func makeUIView(context: Context) -> AVRoutePickerView {
        let view = AVRoutePickerView()
        view.prioritizesVideoDevices = false
        view.activeTintColor = .systemBlue
        view.tintColor = .systemBlue
        return view
    }
    func updateUIView(_ uiView: AVRoutePickerView, context: Context) {}
}

private extension View {
    func cardStyle() -> some View {
        self.background(Color(white: 0.105)).cornerRadius(16)
            .overlay(RoundedRectangle(cornerRadius: 16).stroke(Color.white.opacity(0.035), lineWidth: 1))
    }
}
''')

m = model.read_text()
m = m.replace('    var driveSync = GoogleDriveSync()\n', '', 1)
m = m.replace('''                "audioStatus": audio.statusText,\n                "driveStatus": driveSync.statusText,\n                "drivePendingCount": driveSync.pendingCount,\n                "updatedAt": iso.string(from: Date())\n''','''                "audioStatus": audio.statusText,\n                "inputName": audio.inputName,\n                "outputName": audio.outputName,\n                "updatedAt": iso.string(from: Date())\n''',1)
m = m.replace('''            if let err = driveSync.lastError { payload["driveLastError"] = err }\n''','',1)
m = m.replace('''    func requestPermissions() {\n        audio.requestMicPermission { _ in }\n        transcription.requestAuthorization()\n    }\n''','''    func requestPermissions() {\n        audio.requestMicPermission { [weak self] _ in self?.audio.refreshAudioRoutes() }\n    }\n''',1)
model.write_text(m)

app.write_text(r'''import SwiftUI

@main
struct WearMemoryApp: App {
    @UIApplicationDelegateAdaptor(WearMemoryAppDelegate.self) private var appDelegate
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
        }
    }
}
''')

# Google OAuth belongs to WearMemory Text now. Keep only the Audio integration URL scheme.
subprocess.run(['/usr/libexec/PlistBuddy','-c','Delete :CFBundleURLTypes:0',str(info)], check=True)
subprocess.run(['/usr/libexec/PlistBuddy','-c','Set :CFBundleShortVersionString 1.6.8',str(info)], check=True)
subprocess.run(['/usr/libexec/PlistBuddy','-c','Set :CFBundleVersion 26',str(info)], check=True)
