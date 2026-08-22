import SwiftUI

struct ContentView: View {
    @State private var status = "Bereit"
    @State private var transcript = ""
    @State private var sourceName = "—"
    @State private var audioTime = "—"
    @State private var processingTime = "—"
    @State private var outputName = "—"
    @State private var isRunning = false
    @State private var lastStage = WhisperEngine.lastStage()

    private let engine = WhisperEngine()

    var body: some View {
        NavigationView {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    GroupBox(label: Text("Lokales Whisper")) {
                        VStack(alignment: .leading, spacing: 8) {
                            row("Modell", "Whisper Base")
                            row("Sprache", "Deutsch (de)")
                            row("Verarbeitung", "100 % offline")
                            row("Threads", "1 (A10 Safe)")
                            row("Build", "6")
                        }.frame(maxWidth: .infinity, alignment: .leading)
                    }

                    Button(action: testAudio) {
                        Text("1. M4A / 16 kHz testen").frame(maxWidth: .infinity).padding(.vertical, 8)
                    }.buttonStyle(.borderedProminent).disabled(isRunning)

                    Button(action: testModel) {
                        Text("2. Whisper Base laden testen").frame(maxWidth: .infinity).padding(.vertical, 8)
                    }.buttonStyle(.borderedProminent).disabled(isRunning)

                    Button(action: runWhisper) {
                        HStack {
                            if isRunning { ProgressView().padding(.trailing, 6) }
                            Text("3. Whisper erkennen").frame(maxWidth: .infinity)
                        }.padding(.vertical, 8)
                    }.buttonStyle(.borderedProminent).disabled(isRunning)

                    GroupBox(label: Text("Diagnose")) {
                        VStack(alignment: .leading, spacing: 7) {
                            Text(status).font(.headline)
                            row("Letzte Stufe", lastStage)
                            row("Quelle", sourceName)
                            row("Audio", audioTime)
                            row("Whisper", processingTime)
                            row("TXT", outputName)
                        }.frame(maxWidth: .infinity, alignment: .leading)
                    }

                    GroupBox(label: Text("Erkannter Text")) {
                        Text(transcript.isEmpty ? "Noch kein Ergebnis." : transcript)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }.padding()
            }
            .navigationTitle("WearMemory Whisper")
            .onAppear { lastStage = WhisperEngine.lastStage() }
        }
    }

    @ViewBuilder private func row(_ title: String, _ value: String) -> some View {
        HStack(alignment: .top) {
            Text(title + ":").foregroundColor(.secondary)
            Spacer(minLength: 8)
            Text(value).multilineTextAlignment(.trailing)
        }
    }

    private func resetRun() {
        isRunning = true
        transcript = ""
        sourceName = "—"
        audioTime = "—"
        processingTime = "—"
        outputName = "—"
    }

    private func testAudio() {
        resetRun(); status = "Teste M4A → 16 kHz Mono…"
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                let r = try engine.probeLatestAudio()
                DispatchQueue.main.async {
                    sourceName = r.sourceName
                    audioTime = String(format: "%.1f s / %d Samples", r.audioSeconds, r.sampleCount)
                    lastStage = WhisperEngine.lastStage()
                    status = "Audio-Konvertierung OK"
                    isRunning = false
                }
            } catch {
                DispatchQueue.main.async {
                    lastStage = WhisperEngine.lastStage()
                    status = "Fehler: \(error.localizedDescription)"
                    isRunning = false
                }
            }
        }
    }

    private func testModel() {
        resetRun(); status = "Teste nur Whisper Base laden/freigeben…"
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                let r = try engine.probeModelLoad()
                DispatchQueue.main.async {
                    processingTime = String(format: "Base geladen in %.2f s", r.loadSeconds)
                    lastStage = WhisperEngine.lastStage()
                    status = "Whisper Base laden/freigeben OK"
                    isRunning = false
                }
            } catch {
                DispatchQueue.main.async {
                    lastStage = WhisperEngine.lastStage()
                    status = "Fehler: \(error.localizedDescription)"
                    isRunning = false
                }
            }
        }
    }

    private func runWhisper() {
        resetRun(); status = "Whisper Diagnose + Safe läuft…"
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                let r = try engine.transcribeLatest()
                DispatchQueue.main.async {
                    sourceName = r.sourceName
                    audioTime = String(format: "%.1f s", r.audioSeconds)
                    processingTime = String(format: "%.1f s", r.processingSeconds)
                    outputName = r.outputURL.lastPathComponent
                    transcript = r.text
                    lastStage = WhisperEngine.lastStage()
                    status = r.text.isEmpty ? "Fertig, kein Text" : "Fertig"
                    isRunning = false
                }
            } catch {
                DispatchQueue.main.async {
                    lastStage = WhisperEngine.lastStage()
                    status = "Fehler: \(error.localizedDescription)"
                    isRunning = false
                }
            }
        }
    }
}
