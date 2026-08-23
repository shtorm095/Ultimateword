from pathlib import Path

root = Path('/tmp/wmtext121-src/WearMemoryText')
processor = root / 'TextProcessor.swift'
drive = root / 'TextDriveSync.swift'

for path in (processor, drive):
    if not path.exists():
        raise SystemExit(f'missing {path}')

p = processor.read_text()
old = '''            var queue = loadQueue(); queue.removeAll { $0.id == item.id }; saveQueue(queue)
            stopFileDeadline()
            activeItemID = nil
            setProcessingLocked(false)
            DispatchQueue.main.async {
                self.lastResult = result
                self.lastError = warnings.isEmpty ? nil : warnings.joined(separator: " | ")
                if text.isEmpty {
                    self.statusText = "Готово · речь не найдена"
                } else if warnings.isEmpty {
                    self.statusText = "Готово"
                } else {
                    self.statusText = "Готово · с предупреждением"
                }
                self.onStateChanged?()
                self.onAudioReady?(sourceURL)
                self.onJournalUpdated?(transcriptFile)
            }
            try? fm.removeItem(at: speechTempDirectory)
            processNextLocked()
'''
new = '''            var queue = loadQueue(); queue.removeAll { $0.id == item.id }; saveQueue(queue)
            stopFileDeadline()
            activeItemID = nil
            setProcessingLocked(false)

            let cleanText = text.trimmingCharacters(in: .whitespacesAndNewlines)
            let shouldDeleteSourceAudio = warnings.isEmpty && !cleanText.isEmpty

            DispatchQueue.main.async {
                self.lastResult = result
                self.lastError = warnings.isEmpty ? nil : warnings.joined(separator: " | ")
                if text.isEmpty {
                    self.statusText = "Готово · речь не найдена"
                } else if warnings.isEmpty {
                    self.statusText = "Готово"
                } else {
                    self.statusText = "Готово · с предупреждением"
                }
                self.onStateChanged?()
                self.onJournalUpdated?(transcriptFile)
                if !shouldDeleteSourceAudio {
                    self.onAudioReady?(sourceURL)
                }
            }

            // A clean, non-empty final transcript is the durable result. Once it is
            // written, the source M4A is no longer needed locally and must not be
            // uploaded to Drive. Keep audio for empty results, warnings and failures.
            if shouldDeleteSourceAudio {
                try fm.removeItem(at: sourceURL)
                let sidecar = sourceURL.deletingPathExtension().appendingPathExtension("meta.json")
                try? fm.removeItem(at: sidecar)
            }

            try? fm.removeItem(at: speechTempDirectory)
            processNextLocked()
'''
if old not in p:
    raise SystemExit('finishSuccess completion block not found')
p = p.replace(old, new, 1)
if p.count('let shouldDeleteSourceAudio = warnings.isEmpty && !cleanText.isEmpty') != 1:
    raise SystemExit('successful-audio deletion invariant failed')
processor.write_text(p)

d = drive.read_text()
old_gate = '''            do {
                let inbox = try SharedTextPaths(fileManager: self.fm).audioInbox
                let sourceM4A = inbox.appendingPathComponent(base).appendingPathExtension("m4a")
                guard self.fm.fileExists(atPath: sourceM4A.path) else {
                    self.setError("Audio Lesen: нет исходного M4A для \\(sourceURL.lastPathComponent)")
                    return
                }
            } catch {
                self.setError("Audio Lesen: \\(error.localizedDescription)")
                return
            }

'''
if old_gate not in d:
    raise SystemExit('TXT source-M4A gate not found')
d = d.replace(old_gate, '', 1)
if 'нет исходного M4A' in d:
    raise SystemExit('source-M4A gate residue remains')
drive.write_text(d)

print('patched: clean successful non-empty transcript deletes local M4A; warnings/errors keep audio')
