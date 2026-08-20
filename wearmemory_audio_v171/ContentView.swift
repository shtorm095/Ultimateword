import SwiftUI

struct ContentView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        TabView {
            home
                .tabItem { Label("Главная", systemImage: "house.fill") }
            recordings
                .tabItem { Label("Записи", systemImage: "folder.fill") }
            settings
                .tabItem { Label("Настройки", systemImage: "gearshape.fill") }
        }
        .accentColor(.blue)
        .preferredColorScheme(.dark)
        .onAppear { model.requestPermissions() }
    }

    private var home: some View {
        screen {
            Text("WearMemory Audio").font(.system(size: 36, weight: .bold, design: .rounded))
            title("Запись")
            recorderCard
            title("Google Drive")
            DriveCard(drive: model.driveSync, detailed: false)
            title("Последние записи")
            audioList(limit: 6)
        }
    }

    private var recordings: some View {
        screen {
            Text("Записи").font(.system(size: 34, weight: .bold, design: .rounded))
            title("Локальное хранилище")
            VStack(spacing: 10) {
                info("waveform", "Фрагментов", "\(model.audio.segmentCount) / 480", .blue)
                info("externaldrive.fill", "Размер", bytes(model.audio.bufferBytes), .purple)
                info("clock.fill", "Фрагмент", "3 минуты", .orange)
            }.card()
            title("Аудиофайлы")
            audioList(limit: 12)
        }
    }

    private var settings: some View {
        screen {
            Text("Настройки").font(.system(size: 34, weight: .bold, design: .rounded))
            title("Устройство")
            VStack(spacing: 10) {
                info("mic.fill", "Микрофон", model.audio.inputName, .green)
                if model.batteryLevel >= 0 {
                    info("battery.50", "Батарея", "\(Int(model.batteryLevel * 100))%", .green)
                }
                info("archivebox.fill", "Буфер", "до 480 фрагментов", .blue)
            }.card()
            title("Google Drive")
            DriveCard(drive: model.driveSync, detailed: true)
            title("Интеграция")
            VStack(spacing: 10) {
                info("link", "Пассивный мост", "готов", .green)
                info("number", "Версия протокола", "1", .blue)
                info("square.stack.3d.up.fill", "Для", "WearMemory Text", .purple)
            }.card()
        }
    }

    private var recorderCard: some View {
        VStack(spacing: 14) {
            Button {
                model.audio.isRecording ? model.audio.stop() : model.audio.start()
            } label: {
                VStack(spacing: 10) {
                    ZStack {
                        Circle()
                            .fill(model.audio.isRecording ? Color.red : Color.blue)
                            .frame(width: 118, height: 118)
                            .shadow(color: (model.audio.isRecording ? Color.red : Color.blue).opacity(0.55), radius: 14)
                        Circle().stroke(Color.white.opacity(0.18), lineWidth: 2).frame(width: 132, height: 132)
                        Image(systemName: model.audio.isRecording ? "stop.fill" : "record.circle")
                            .font(.system(size: 40, weight: .bold)).foregroundColor(.white)
                    }
                    Text(model.audio.isRecording ? "Остановить запись" : "Начать запись")
                        .font(.headline)
                        .foregroundColor(model.audio.isRecording ? .red : .blue)
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.plain)

            HStack {
                Image(systemName: "waveform").foregroundColor(.cyan)
                Text(model.audio.statusText).foregroundColor(.secondary)
                Spacer()
                if model.driveSync.pendingCount > 0 {
                    Text("Drive: \(model.driveSync.pendingCount)").font(.caption).foregroundColor(.blue)
                }
            }
        }
        .padding(14)
        .card()
    }

    private func audioList(limit: Int) -> some View {
        VStack(spacing: 0) {
            if model.audio.recentSegments.isEmpty {
                HStack {
                    Image(systemName: "waveform").foregroundColor(.blue)
                    Text("Пока нет завершённых записей").foregroundColor(.secondary)
                    Spacer()
                }.padding(14)
            } else {
                ForEach(Array(model.audio.recentSegments.prefix(limit).enumerated()), id: \.element.id) { index, item in
                    if index > 0 { Divider().background(Color.white.opacity(0.08)) }
                    HStack(spacing: 10) {
                        Image(systemName: "doc.badge.waveform.fill").font(.title2).foregroundColor(.cyan).frame(width: 28)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(item.fileName).font(.subheadline.weight(.semibold)).foregroundColor(.white).lineLimit(1)
                            Text(clock(item.createdAt)).font(.caption2).foregroundColor(.secondary)
                        }
                        Spacer()
                        VStack(alignment: .trailing, spacing: 3) {
                            Text(duration(item.duration)).font(.caption.monospacedDigit()).foregroundColor(.secondary)
                            Text(bytes(item.sizeBytes)).font(.caption2).foregroundColor(.secondary)
                        }
                        Button {
                            model.audio.togglePlayback(item.url)
                        } label: {
                            Image(systemName: model.audio.isPlaying(item.url) ? "stop.circle.fill" : "play.circle.fill")
                                .font(.system(size: 30))
                                .foregroundColor(model.audio.isPlaying(item.url) ? .red : .blue)
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel(model.audio.isPlaying(item.url) ? "Остановить" : "Воспроизвести")
                    }
                    .padding(.horizontal, 12).padding(.vertical, 10)
                }
            }
        }.card()
    }

    private func screen<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        ZStack {
            Color.black.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 18) { content() }
                    .padding(.horizontal, 16).padding(.top, 10).padding(.bottom, 26)
            }
        }
    }

    private func title(_ text: String) -> some View {
        Text(text).font(.title2.bold()).foregroundColor(.white)
    }

    private func info(_ icon: String, _ name: String, _ value: String, _ tint: Color) -> some View {
        HStack(spacing: 10) {
            Image(systemName: icon).foregroundColor(tint).frame(width: 24)
            Text(name).foregroundColor(.white)
            Spacer()
            Text(value).foregroundColor(.secondary).multilineTextAlignment(.trailing)
        }
        .font(.subheadline).padding(.horizontal, 13).padding(.vertical, 4)
    }

    private func clock(_ date: Date) -> String {
        let f = DateFormatter(); f.dateFormat = "HH:mm:ss"; return f.string(from: date)
    }

    private func duration(_ seconds: TimeInterval) -> String {
        guard seconds.isFinite, seconds > 0 else { return "--:--" }
        let total = Int(seconds.rounded()); return String(format: "%02d:%02d", total / 60, total % 60)
    }

    private func bytes(_ value: Int64) -> String {
        ByteCountFormatter.string(fromByteCount: value, countStyle: .file)
    }
}

private struct DriveCard: View {
    @ObservedObject var drive: GoogleDriveSync
    let detailed: Bool

    private var ready: Bool { drive.isAuthorized && drive.foldersAuthorized }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Image(systemName: ready ? "checkmark.icloud.fill" : "icloud.and.arrow.up.fill")
                    .font(.title2).foregroundColor(ready ? .green : .orange).frame(width: 32)
                VStack(alignment: .leading, spacing: 3) {
                    Text("Google Drive").font(.headline).foregroundColor(.white)
                    Text(drive.statusText).font(.caption).foregroundColor(ready ? .green : .orange)
                }
                Spacer()
                if drive.pendingCount > 0 {
                    Text("Очередь \(drive.pendingCount)").font(.caption.weight(.semibold)).foregroundColor(.blue)
                }
            }.padding(14)

            Divider().background(Color.white.opacity(0.08))

            HStack(spacing: 10) {
                Image(systemName: "music.note").font(.title2).foregroundColor(.green).frame(width: 32)
                VStack(alignment: .leading, spacing: 3) {
                    Text("Аудио → Audio Hören").foregroundColor(.white)
                    Text(drive.audioFolderDisplay).font(.caption2).foregroundColor(.secondary)
                }
                Spacer()
                Image(systemName: drive.foldersAuthorized ? "checkmark.circle.fill" : "circle")
                    .foregroundColor(drive.foldersAuthorized ? .green : .secondary)
            }.padding(14)

            if detailed {
                Divider().background(Color.white.opacity(0.08))
                HStack {
                    Image(systemName: "arrow.triangle.2.circlepath").foregroundColor(.blue).frame(width: 32)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Автосинхронизация").foregroundColor(.white)
                        Text("Очередь: \(drive.pendingCount)").font(.caption).foregroundColor(.secondary)
                    }
                    Spacer()
                    Toggle("", isOn: $drive.syncEnabled).labelsHidden()
                }.padding(14)
            }

            Divider().background(Color.white.opacity(0.08))
            HStack(spacing: 10) {
                Button(ready ? "Переподключить" : "Подключить Google Drive") { drive.connect() }
                    .buttonStyle(.borderedProminent)
                if drive.isAuthorized {
                    Button("Отключить", role: .destructive) { drive.disconnect() }.buttonStyle(.bordered)
                }
                Spacer()
            }.padding(14)

            if let error = drive.lastError {
                Divider().background(Color.white.opacity(0.08))
                Text(error).font(.caption).foregroundColor(.orange).frame(maxWidth: .infinity, alignment: .leading).padding(14)
            }
        }.card()
    }
}

private extension View {
    func card() -> some View {
        self.background(Color(white: 0.105)).cornerRadius(16)
            .overlay(RoundedRectangle(cornerRadius: 16).stroke(Color.white.opacity(0.035), lineWidth: 1))
    }
}
