from pathlib import Path
import subprocess

root = Path('/tmp/wmtext111-src')
content = root/'WearMemoryText/ContentView.swift'
info = root/'WearMemoryText/Info.plist'

content.write_text(r'''import SwiftUI
import Speech

struct ContentView: View {
    @EnvironmentObject var model: TextAppModel
    @Environment(\.openURL) private var openURL

    var body: some View {
        TabView {
            home
                .tabItem { Label("Главная", systemImage: "waveform.and.mic") }
            texts
                .tabItem { Label("Тексты", systemImage: "doc.text.fill") }
        }
        .accentColor(.blue)
        .preferredColorScheme(.dark)
    }

    private var home: some View {
        screen {
            Text("WearMemory Text")
                .font(.system(size: 34, weight: .bold, design: .rounded))

            title("WearMemory Audio")
            VStack(spacing: 10) {
                info("record.circle.fill", "Состояние", model.audioIsRecording ? "Записывает" : model.audioStatus, model.audioIsRecording ? .red : .secondary)
                info("waveform", "Готовые M4A", "\(model.inboxCount)", .cyan)
                info("link", "Общая папка", model.appGroupStatus, model.appGroupStatus == "Доступна" ? .green : .red)
                Divider().background(Color.white.opacity(0.08))
                Button {
                    if let url = URL(string: "wearmemory-audio://open") { openURL(url) }
                } label: {
                    Label(model.audioIsRecording ? "Открыть Audio для остановки" : "Открыть WearMemory Audio", systemImage: "arrow.up.forward.app.fill")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
            }
            .padding(14)
            .card()

            title("Распознавание")
            VStack(spacing: 12) {
                HStack {
                    Image(systemName: "character.book.closed.fill").foregroundColor(.purple).frame(width: 26)
                    Text("Язык")
                    Spacer()
                    Picker("Язык", selection: $model.language) {
                        ForEach(TextLanguage.allCases) { Text($0.title).tag($0) }
                    }
                    .pickerStyle(.menu)
                }
                Divider().background(Color.white.opacity(0.08))
                info("checkmark.circle.fill", "Speech", speechText, model.processor.speechAuthorization == .authorized ? .green : .orange)
                info("waveform.badge.magnifyingglass", "Состояние", model.processor.statusText, model.processor.lastError == nil ? .green : .orange)
                info("tray.full.fill", "Очередь", "\(model.processor.pendingCount)", .blue)
                info("timer", "Лимит файла", "3 минуты", .cyan)
                Divider().background(Color.white.opacity(0.08))
                Button {
                    model.processAll()
                } label: {
                    Label(model.processor.isProcessing ? "Обработка…" : "Обработать очередь", systemImage: "play.fill")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .disabled(model.processor.speechAuthorization != .authorized || model.processor.isProcessing)
                if let error = model.processor.lastError {
                    Text(error)
                        .font(.caption)
                        .foregroundColor(.orange)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .padding(14)
            .card()

            title("Google Drive")
            driveCard

            if let result = model.processor.lastResult {
                title("Последний результат")
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Image(systemName: result.warnings == nil ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                            .foregroundColor(result.warnings == nil ? .green : .orange)
                        Text(result.warnings == nil ? "Распознано полностью" : "Есть предупреждения")
                            .font(.headline)
                    }
                    Text(result.sourceFileName).font(.caption).foregroundColor(.secondary)
                    Text(result.text.isEmpty ? "Речь не найдена" : result.text)
                        .foregroundColor(.white)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(14)
                .card()
            }
        }
    }

    private var texts: some View {
        screen {
            Text("Тексты")
                .font(.system(size: 34, weight: .bold, design: .rounded))
            title("Дневные TXT")
            VStack(spacing: 0) {
                if model.journalFiles.isEmpty {
                    HStack {
                        Image(systemName: "doc.text").foregroundColor(.blue)
                        Text("Пока нет TXT").foregroundColor(.secondary)
                        Spacer()
                    }
                    .padding(14)
                } else {
                    ForEach(Array(model.journalFiles.enumerated()), id: \.element.path) { index, url in
                        if index > 0 { Divider().background(Color.white.opacity(0.08)) }
                        HStack {
                            Image(systemName: "doc.text.fill").foregroundColor(.blue).font(.title2)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(url.lastPathComponent).foregroundColor(.white)
                                if let size = try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize {
                                    Text(ByteCountFormatter.string(fromByteCount: Int64(size), countStyle: .file))
                                        .font(.caption2).foregroundColor(.secondary)
                                }
                            }
                            Spacer()
                        }
                        .padding(14)
                    }
                }
            }
            .card()
        }
    }

    private var driveCard: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Image(systemName: driveReady ? "checkmark.icloud.fill" : "icloud.slash.fill")
                    .font(.title2)
                    .foregroundColor(driveReady ? .green : .orange)
                VStack(alignment: .leading, spacing: 3) {
                    Text(driveReady ? "Подключено" : "Не подключено")
                        .font(.headline)
                    Text(model.drive.statusText)
                        .font(.caption)
                        .foregroundColor(driveReady ? .green : .orange)
                }
                Spacer()
                if model.drive.pendingCount > 0 {
                    Text("Очередь \(model.drive.pendingCount)")
                        .font(.caption.weight(.semibold))
                        .foregroundColor(.blue)
                }
            }
            .padding(14)
            Divider().background(Color.white.opacity(0.08))
            info("doc.text.fill", "Полный текст", "Audio Lesen", .purple)
            Divider().background(Color.white.opacity(0.08))
            info("music.note", "needs_pc", "Audio Hören", .green)
            Divider().background(Color.white.opacity(0.08))
            HStack(spacing: 10) {
                Button("Проверить доступ") { model.drive.refreshAuthorization() }
                    .buttonStyle(.bordered)
                if !model.drive.isAuthorized {
                    Button("Подключить в Audio") {
                        if let url = URL(string: "wearmemory-audio://open") { openURL(url) }
                    }
                    .buttonStyle(.borderedProminent)
                }
                Spacer()
            }
            .padding(14)
            if let error = model.drive.lastError {
                Divider().background(Color.white.opacity(0.08))
                Text(error)
                    .font(.caption)
                    .foregroundColor(.orange)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(14)
            }
        }
        .card()
    }

    private var driveReady: Bool {
        model.drive.isAuthorized && model.drive.folderAuthorized
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
            ScrollView {
                VStack(alignment: .leading, spacing: 18) { content() }
                    .padding(.horizontal, 16)
                    .padding(.top, 10)
                    .padding(.bottom, 26)
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
            Text(value).foregroundColor(.secondary).multilineTextAlignment(.trailing).lineLimit(2)
        }
        .font(.subheadline)
        .padding(.horizontal, 13)
        .padding(.vertical, 4)
    }
}

private extension View {
    func card() -> some View {
        self.background(Color(white: 0.105)).cornerRadius(16)
            .overlay(RoundedRectangle(cornerRadius: 16).stroke(Color.white.opacity(0.035), lineWidth: 1))
    }
}
''')

subprocess.run(['/usr/libexec/PlistBuddy','-c','Set :CFBundleShortVersionString 1.1.1',str(info)], check=True)
subprocess.run(['/usr/libexec/PlistBuddy','-c','Set :CFBundleVersion 11',str(info)], check=True)
