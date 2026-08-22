import SwiftUI

struct ContentView: View {
    @State private var status = "Bereit"
    @State private var transcript = ""
    @State private var sourceName = "—"
    @State private var audioTime = "—"
    @State private var processingTime = "—"
    @State private var outputName = "—"
    @State private var isRunning = false

    private let engine = WhisperEngine()

    var body: some View {
        NavigationView {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    GroupBox(label: Text("Lokales Whisper")) {
                        VStack(alignment: .leading, spacing: 8) {
                            row("Modell", "Whisper Base")
                            row("Sprache", "Deutsch (de)")
                            row("Verarbeitung", "100 % offline")
                            row("Threads", "2")
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    Button(action: run) {
                        HStack {
                            if isRunning { ProgressView().padding(.trailing, 6) }
                            Text(isRunning ? "Verarbeitung läuft…" : "Letzte M4A erkennen")
                                .frame(maxWidth: .infinity)
                        }
                        .padding(.vertical, 10)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(isRunning)

                    GroupBox(label: Text("Status")) {
                        VStack(alignment: .leading, spacing: 7) {
                            Text(status).font(.headline)
                            row("Quelle", sourceName)
                            row("Audio", audioTime)
                            row("Whisper", processingTime)
                            row("TXT", outputName)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    GroupBox(label: Text("Erkannter Text")) {
                        Text(transcript.isEmpty ? "Noch kein Ergebnis." : transcript)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .padding()
            }
            .navigationTitle("WearMemory Whisper")
        }
    }

    @ViewBuilder
    private func row(_ title: String, _ value: String) -> some View {
        HStack(alignment: .top) {
            Text(title + ":").foregroundColor(.secondary)
            Spacer(minLength: 8)
            Text(value).multilineTextAlignment(.trailing)
        }
    }

    private func run() {
        isRunning = true
        status = "M4A → 16 kHz Mono → Whisper…"
        transcript = ""
        sourceName = "—"
        audioTime = "—"
        processingTime = "—"
        outputName = "—"

        DispatchQueue.global(qos: .userInitiated).async {
            do {
                let result = try engine.transcribeLatest()
                DispatchQueue.main.async {
                    sourceName = result.sourceName
                    audioTime = String(format: "%.1f s", result.audioSeconds)
                    processingTime = String(format: "%.1f s", result.processingSeconds)
                    outputName = result.outputURL.lastPathComponent
                    transcript = result.text
                    status = result.text.isEmpty ? "Fertig, aber kein Text erkannt" : "Fertig"
                    isRunning = false
                }
            } catch {
                DispatchQueue.main.async {
                    status = "Fehler: \(error.localizedDescription)"
                    isRunning = false
                }
            }
        }
    }
}
