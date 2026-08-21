import SwiftUI
import Speech

struct ContentView: View {
    @EnvironmentObject var model: TextAppModel

    var body: some View {
        TabView {
            home.tabItem { Label("Главная", systemImage: "text.bubble.fill") }
            texts.tabItem { Label("Тексты", systemImage: "doc.text.fill") }
            settings.tabItem { Label("Настройки", systemImage: "gearshape.fill") }
        }
        .accentColor(.blue)
        .preferredColorScheme(.dark)
    }

    private var home: some View {
        screen {
            Text("WearMemory Text").font(.system(size: 34, weight: .bold, design: .rounded))
            title("Источник")
            VStack(spacing: 10) {
                info("link", "Общая папка", model.appGroupStatus, model.appGroupStatus == "Доступна" ? .green : .red)
                info("waveform", "M4A в AudioInbox", "\(model.inboxCount)", .cyan)
                info("record.circle", "WearMemory Audio", model.audioIsRecording ? "Записывает" : model.audioStatus, model.audioIsRecording ? .red : .secondary)
            }.card()

            title("Распознавание")
            VStack(spacing: 12) {
                info("waveform.badge.magnifyingglass", "Состояние", model.processor.statusText, model.processor.lastError == nil ? .green : .orange)
                info("tray.full.fill", "Очередь", "\(model.processor.pendingCount)", .blue)
                info("character.book.closed.fill", "Язык", model.language.title, .purple)
                Button {
                    model.processAll()
                } label: {
                    Label(model.processor.isProcessing ? "Обработка…" : "Обработать очередь", systemImage: "play.fill")
                        .frame(maxWidth: .infinity).padding(.vertical, 9)
                }
                .buttonStyle(.borderedProminent)
                .disabled(model.processor.speechAuthorization != .authorized || model.processor.isProcessing)
                if let partial = model.processor.lastPartialText, !partial.isEmpty {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Промежуточный текст сохранён").font(.caption.bold()).foregroundColor(.cyan)
                        Text(partial).font(.caption).foregroundColor(.secondary)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
                if let error = model.processor.lastError {
                    Text(error).font(.caption).foregroundColor(.orange).frame(maxWidth: .infinity, alignment: .leading)
                }
            }.padding(14).card()

            if let result = model.processor.lastResult {
                title("Последний текст")
                VStack(alignment: .leading, spacing: 8) {
                    Text(result.sourceFileName).font(.caption).foregroundColor(.secondary)
                    Text(result.text.isEmpty ? "Речь не найдена" : result.text).foregroundColor(.white)
                }.frame(maxWidth: .infinity, alignment: .leading).padding(14).card()
            }

            title("Google Drive")
            driveCard
        }
    }

    private var texts: some View {
        screen {
            Text("Тексты").font(.system(size: 34, weight: .bold, design: .rounded))
            title("Дневные TXT")
            VStack(spacing: 0) {
                if model.journalFiles.isEmpty {
                    HStack { Image(systemName: "doc.text").foregroundColor(.blue); Text("Пока нет TXT").foregroundColor(.secondary); Spacer() }.padding(14)
                } else {
                    ForEach(Array(model.journalFiles.enumerated()), id: \.element.path) { index, url in
                        if index > 0 { Divider().background(Color.white.opacity(0.08)) }
                        HStack {
                            Image(systemName: "doc.text.fill").foregroundColor(.blue).font(.title2)
                            Text(url.lastPathComponent).foregroundColor(.white)
                            Spacer()
                            if let size = try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize {
                                Text(ByteCountFormatter.string(fromByteCount: Int64(size), countStyle: .file)).font(.caption).foregroundColor(.secondary)
                            }
                        }.padding(14)
                    }
                }
            }.card()
        }
    }

    private var settings: some View {
        screen {
            Text("Настройки").font(.system(size: 34, weight: .bold, design: .rounded))
            title("Speech")
            VStack(spacing: 12) {
                HStack {
                    Image(systemName: "character.book.closed.fill").foregroundColor(.purple).frame(width: 28)
                    Text("Язык")
                    Spacer()
                    Picker("Язык", selection: $model.language) {
                        ForEach(TextLanguage.allCases) { Text($0.title).tag($0) }
                    }.pickerStyle(.menu)
                }
                Divider().background(Color.white.opacity(0.08))
                info("checkmark.circle.fill", "Разрешение Speech", speechText, model.processor.speechAuthorization == .authorized ? .green : .orange)
            }.padding(14).card()

            title("Google Drive")
            driveCard

            title("Интеграция")
            VStack(spacing: 10) {
                info("link", "App Group", "group.local.pavel.WearMemory", .green)
                info("arrow.down.doc.fill", "Вход", "AudioInbox", .cyan)
                info("arrow.up.doc.fill", "Выход", "Audio Lesen", .blue)
                info("link.badge.plus", "URL запуска", "wearmemory-text://process", .purple)
                info("number", "Версия моста", "1", .blue)
            }.card()
        }
    }

    private var driveCard: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Image(systemName: model.drive.folderAuthorized ? "checkmark.icloud.fill" : "icloud.slash.fill")
                    .font(.title2).foregroundColor(model.drive.folderAuthorized ? .green : .orange).frame(width: 32)
                VStack(alignment: .leading, spacing: 3) {
                    Text("TXT → Audio Lesen").font(.headline)
                    Text(model.drive.statusText).font(.caption).foregroundColor(model.drive.folderAuthorized ? .green : .orange)
                }
                Spacer()
                if model.drive.pendingCount > 0 { Text("Очередь \(model.drive.pendingCount)").font(.caption).foregroundColor(.blue) }
            }.padding(14)
            Divider().background(Color.white.opacity(0.08))
            HStack {
                Image(systemName: "arrow.triangle.2.circlepath").foregroundColor(.blue).frame(width: 32)
                Text("Автосинхронизация")
                Spacer()
                Toggle("", isOn: $model.drive.syncEnabled).labelsHidden()
            }.padding(14)
            Divider().background(Color.white.opacity(0.08))
            HStack {
                Button("Проверить доступ") { model.drive.refreshAuthorization() }.buttonStyle(.bordered)
                Spacer()
            }.padding(14)
            if let error = model.drive.lastError {
                Divider().background(Color.white.opacity(0.08))
                Text(error).font(.caption).foregroundColor(.orange).frame(maxWidth: .infinity, alignment: .leading).padding(14)
            }
        }.card()
    }

    private var speechText: String {
        switch model.processor.speechAuthorization {
        case .authorized: return "Разрешено"
        case .denied: return "Запрещено"
        case .restricted: return "Ограничено"
        case .notDetermined: return "Не запрошено"
        @unknown default: return "Неизвестно"
        }
    }

    private func screen<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        ZStack {
            Color.black.ignoresSafeArea()
            ScrollView { VStack(alignment: .leading, spacing: 18) { content() }.padding(.horizontal, 16).padding(.top, 10).padding(.bottom, 26) }
        }
    }
    private func title(_ text: String) -> some View { Text(text).font(.title2.bold()).foregroundColor(.white) }
    private func info(_ icon: String, _ name: String, _ value: String, _ tint: Color) -> some View {
        HStack(spacing: 10) {
            Image(systemName: icon).foregroundColor(tint).frame(width: 24)
            Text(name).foregroundColor(.white)
            Spacer()
            Text(value).foregroundColor(.secondary).multilineTextAlignment(.trailing).lineLimit(2)
        }.font(.subheadline).padding(.horizontal, 13).padding(.vertical, 4)
    }
}

private extension View {
    func card() -> some View {
        self.background(Color(white: 0.105)).cornerRadius(16)
            .overlay(RoundedRectangle(cornerRadius: 16).stroke(Color.white.opacity(0.035), lineWidth: 1))
    }
}
