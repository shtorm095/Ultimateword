from pathlib import Path

p = Path('/tmp/wmtext112-src/WearMemoryText/ContentView.swift')
s = p.read_text()

s = s.replace('''    private var player: AVAudioPlayer?\n    private var timer: Timer?\n\n    deinit { timer?.invalidate() }\n''','''    private var player: AVAudioPlayer?\n    private var timer: Timer?\n    private var retentionTimer: Timer?\n    private let retentionSeconds: TimeInterval = 24 * 60 * 60\n\n    override init() {\n        super.init()\n        retentionTimer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in\n            self?.refresh()\n        }\n    }\n\n    deinit {\n        timer?.invalidate()\n        retentionTimer?.invalidate()\n    }\n''',1)

s = s.replace('''        let inbox = root.appendingPathComponent("AudioInbox", isDirectory: true)\n        do {\n            try fm.createDirectory(at: inbox, withIntermediateDirectories: true)\n            let urls = try fm.contentsOfDirectory(\n''','''        let inbox = root.appendingPathComponent("AudioInbox", isDirectory: true)\n        do {\n            try fm.createDirectory(at: inbox, withIntermediateDirectories: true)\n            purgeExpiredAudio(in: inbox)\n            let urls = try fm.contentsOfDirectory(\n''',1)

marker = '''    func playPause(_ url: URL) {\n'''
helper = r'''    private func purgeExpiredAudio(in inbox: URL) {
        guard let urls = try? fm.contentsOfDirectory(
            at: inbox,
            includingPropertiesForKeys: [.contentModificationDateKey],
            options: [.skipsHiddenFiles]
        ) else { return }

        let now = Date()
        for url in urls where url.pathExtension.lowercased() == "m4a" {
            let expiryBase = recordingEndedAt(for: url)
                ?? (try? url.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate)
                ?? now
            guard now.timeIntervalSince(expiryBase) >= retentionSeconds else { continue }

            if currentURL == url {
                stopPlayback(resetSelection: true)
            }
            try? fm.removeItem(at: url)

            let meta = url.deletingPathExtension().appendingPathExtension("meta.json")
            try? fm.removeItem(at: meta)
        }
    }

    private func recordingEndedAt(for audioURL: URL) -> Date? {
        let meta = audioURL.deletingPathExtension().appendingPathExtension("meta.json")
        guard let data = try? Data(contentsOf: meta),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let ended = object["endedAt"] as? String else { return nil }
        return ISO8601DateFormatter().date(from: ended)
    }

'''
if marker not in s:
    raise SystemExit('playPause marker not found')
s = s.replace(marker, helper + marker, 1)

p.write_text(s)
