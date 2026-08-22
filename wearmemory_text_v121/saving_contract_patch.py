from pathlib import Path
import re

root = Path('/tmp/wmtext121-src')
app = root / 'WearMemoryText'
processor = app / 'TextProcessor.swift'
drive = app / 'TextDriveSync.swift'

p = processor.read_text()

# Storage contract: the TXT identity is derived ONLY from the original M4A filename.
# Internal Whisper chunks must never become files or Drive objects.
old_call = '            let transcriptFile = try writeSegmentText(item: item, text: text)\n'
new_call = '            let transcriptFile = try writeSegmentText(sourceURL: sourceURL, text: text)\n'
if old_call not in p:
    raise SystemExit('finishSuccess TXT call not found')
p = p.replace(old_call, new_call, 1)

pattern = re.compile(
    r'    private func writeSegmentText\(item: TextQueueItem, text: String\) throws -> URL \{.*?\n    \}\n\n',
    re.S,
)
replacement = r'''    private func writeSegmentText(sourceURL: URL, text: String) throws -> URL {
        try ensureDirectories()

        // Canonical identity: audio-YYYYMMDD-HHMMSS.m4a -> audio-YYYYMMDD-HHMMSS.txt
        // Never use Whisper piece names, temporary names or processing timestamps here.
        let sourceBase = sourceURL.deletingPathExtension().lastPathComponent
        guard !sourceBase.isEmpty,
              sourceURL.pathExtension.lowercased() == "m4a" else {
            throw NSError(
                domain: "WearMemoryText.Text",
                code: 2,
                userInfo: [NSLocalizedDescriptionKey: "TXT можно сохранить только для исходного M4A"]
            )
        }

        let url = journalsDirectory.appendingPathComponent(sourceBase).appendingPathExtension("txt")
        let clean = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let body = clean.isEmpty ? "" : clean + "\n"
        guard let data = body.data(using: .utf8) else {
            throw NSError(domain: "WearMemoryText.Text", code: 1, userInfo: [NSLocalizedDescriptionKey: "Не удалось создать TXT"])
        }

        // Atomic overwrite makes repeated processing idempotent: same M4A -> same single TXT.
        try data.write(to: url, options: .atomic)
        return url
    }

'''
p, count = pattern.subn(lambda _: replacement, p, count=1)
if count != 1:
    raise SystemExit(f'writeSegmentText replacement count={count}')

# There must be exactly one final TXT write in the production success path.
if p.count('writeSegmentText(sourceURL: sourceURL, text: text)') != 1:
    raise SystemExit('TXT final-write invariant failed')
processor.write_text(p)

# Drive gate: Audio Lesen accepts only a final TXT that has a source M4A with the same basename.
d = drive.read_text()
start = d.index('    func enqueueText(_ sourceURL: URL) {\n')
end = d.index('\n    func enqueueAudio(_ audioURL: URL) {', start)
new_enqueue = r'''    func enqueueText(_ sourceURL: URL) {
        guard syncEnabled else { return }
        workQueue.async {
            guard self.fm.fileExists(atPath: sourceURL.path),
                  sourceURL.pathExtension.lowercased() == "txt" else {
                self.setError("Audio Lesen: финальный TXT не найден")
                return
            }

            let base = sourceURL.deletingPathExtension().lastPathComponent
            guard !base.isEmpty else {
                self.setError("Audio Lesen: неверное имя TXT")
                return
            }

            do {
                let inbox = try SharedTextPaths(fileManager: self.fm).audioInbox
                let sourceM4A = inbox.appendingPathComponent(base).appendingPathExtension("m4a")
                guard self.fm.fileExists(atPath: sourceM4A.path) else {
                    self.setError("Audio Lesen: нет исходного M4A для \(sourceURL.lastPathComponent)")
                    return
                }
            } catch {
                self.setError("Audio Lesen: \(error.localizedDescription)")
                return
            }

            var queue = self.normalizedPendingQueue(self.loadQueue())
            queue.removeAll { item in
                let itemURL = URL(fileURLWithPath: item.path)
                return (item.folderID ?? Self.textFolderID) == Self.textFolderID &&
                       itemURL.lastPathComponent == sourceURL.lastPathComponent
            }
            queue.append(PendingItem(
                id: "text:\(sourceURL.lastPathComponent)",
                path: sourceURL.path,
                folderID: Self.textFolderID,
                mimeType: "text/plain; charset=utf-8"
            ))
            self.saveQueue(self.normalizedPendingQueue(queue))
            self.flushQueueLocked()
        }
    }
'''
d = d[:start] + new_enqueue + d[end:]

# Hard assertions: no random logical ID and no alternate TXT upload path.
if 'id: "text:\\(sourceURL.lastPathComponent):\\(UUID().uuidString)"' in d:
    raise SystemExit('random TXT queue id remains')
if d.count('func enqueueText(_ sourceURL: URL)') != 1:
    raise SystemExit('enqueueText invariant failed')
drive.write_text(d)

print('saving contract enforced: one source M4A -> one canonical TXT -> one idempotent Drive object')
