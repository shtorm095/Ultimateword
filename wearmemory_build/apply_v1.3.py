from pathlib import Path
import sys

root = Path(sys.argv[1])

p = root / 'AppModel.swift'
s = p.read_text()
s = s.replace(
    '    @Published private(set) var batteryLevel: Float = -1\n',
    '    @Published private(set) var batteryLevel: Float = -1\n'
    '    @Published var googleDriveSyncEnabled: Bool = UserDefaults.standard.object(forKey: "googleDriveSyncEnabled") as? Bool ?? true {\n'
    '        didSet { UserDefaults.standard.set(googleDriveSyncEnabled, forKey: "googleDriveSyncEnabled") }\n'
    '    }\n'
)
s = s.replace(
    '        logs.onTextFileUpdated = { [weak self] url in\n            self?.externalTextFolder.syncTextFile(url)\n        }',
    '        logs.onTextFileUpdated = { [weak self] url in\n            guard let self, self.googleDriveSyncEnabled else { return }\n            self.externalTextFolder.syncTextFile(url)\n        }'
)
s = s.replace(
    '        audio.onSegmentCompleted = { [weak self] url, _, _ in\n            self?.externalAudioFolder.syncAudioFile(url)\n        }',
    '        audio.onSegmentCompleted = { [weak self] url, _, _ in\n            guard let self, self.googleDriveSyncEnabled else { return }\n            self.externalAudioFolder.syncAudioFile(url)\n        }'
)
p.write_text(s)

p = root / 'ContentView.swift'
s = p.read_text()
old = '''                    sectionTitle("Папки")
                    storageCard
'''
new = '''                    sectionTitle("Google Drive")
                    VStack(spacing: 0) {
                        HStack(spacing: 12) {
                            Image(systemName: "icloud.and.arrow.up.fill")
                                .font(.title2)
                                .foregroundColor(.blue)
                                .frame(width: 30)
                            VStack(alignment: .leading, spacing: 3) {
                                Text("Сохранять в Google Drive")
                                    .font(.headline)
                                    .foregroundColor(.white)
                                Text(model.googleDriveSyncEnabled ? "Автосохранение включено" : "Автосохранение выключено")
                                    .font(.caption)
                                    .foregroundColor(model.googleDriveSyncEnabled ? .green : .secondary)
                            }
                            Spacer()
                            Toggle("", isOn: $model.googleDriveSyncEnabled)
                                .labelsHidden()
                        }
                        .padding(14)

                        Divider().background(Color.white.opacity(0.08))

                        HStack {
                            Image(systemName: "doc.text.fill")
                                .foregroundColor(.purple)
                                .frame(width: 30)
                            VStack(alignment: .leading, spacing: 3) {
                                Text("Текст")
                                    .foregroundColor(.white)
                                Text(model.externalTextFolder.isConfigured ? "Audio Lesen · подключено" : "Audio Lesen · не выбрано")
                                    .font(.caption)
                                    .foregroundColor(model.externalTextFolder.isConfigured ? .green : .secondary)
                            }
                            Spacer()
                            Button("Выбрать") { showAudioLesenPicker = true }
                                .buttonStyle(.borderedProminent)
                        }
                        .padding(14)

                        Divider().background(Color.white.opacity(0.08))

                        HStack {
                            Image(systemName: "music.note")
                                .foregroundColor(.green)
                                .frame(width: 30)
                            VStack(alignment: .leading, spacing: 3) {
                                Text("Аудио")
                                    .foregroundColor(.white)
                                Text(model.externalAudioFolder.isConfigured ? "Audio Hören · подключено" : "Audio Hören · не выбрано")
                                    .font(.caption)
                                    .foregroundColor(model.externalAudioFolder.isConfigured ? .green : .secondary)
                            }
                            Spacer()
                            Button("Выбрать") { showAudioHoerenPicker = true }
                                .buttonStyle(.borderedProminent)
                        }
                        .padding(14)
                    }
                    .cardStyle()

                    sectionTitle("Папки")
                    storageCard
'''
if old not in s:
    raise SystemExit('settings insertion point not found')
s = s.replace(old, new, 1)
p.write_text(s)
