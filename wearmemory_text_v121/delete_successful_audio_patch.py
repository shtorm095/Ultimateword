from pathlib import Path

root = Path('/tmp/wmtext121-src/WearMemoryText')
processor = root / 'TextProcessor.swift'
drive = root / 'TextDriveSync.swift'

for path in (processor, drive):
    if not path.exists():
        raise SystemExit(f'missing {path}')

p = processor.read_text()

# Base confidence is informational metadata, not a processing warning. The previous
# dual-pass patch put it into warnings, which would incorrectly classify every file
# as problematic and prevent clean-audio deletion.
base_line = '            let baseSummary = "Base score \\(Int((baseTranscript.confidence * 100).rounded()))%"\n'
if base_line not in p:
    raise SystemExit('Base score pseudo-warning marker not found')
p = p.replace(base_line, '', 1)
warning_arg = '                warnings: [baseSummary],\n'
if warning_arg not in p:
    raise SystemExit('Base score warning argument not found')
p = p.replace(warning_arg, '                warnings: [],\n', 1)

# Every processing failure that occurs after a queue item became active is terminal
# for the iPod path: mark it needs_pc and send the original M4A to Audio Hören.
# Keep the old finishFailure implementation as a fallback only when there is no
# recoverable source M4A (for example a queue bookkeeping error).
finish_sig = '    private func finishFailure(itemID: String, message: String) {\n'
finish_preamble = '''    private func finishFailure(itemID: String, message: String) {\n        if activeItemID == itemID,\n           let item = loadQueue().first(where: { $0.id == itemID }),\n           let paths = try? SharedTextPaths(fileManager: fm) {\n            let sourceURL = paths.audioInbox.appendingPathComponent(item.sourceFileName)\n            if fm.fileExists(atPath: sourceURL.path) {\n                markNeedsPC(item: item, sourceURL: sourceURL, reason: message, partialText: "")\n                return\n            }\n        }\n'''
if finish_sig not in p:
    raise SystemExit('finishFailure signature not found')
p = p.replace(finish_sig, finish_preamble, 1)

# A successful function call is not necessarily a clean result. Empty final text or
# any real warning is stored in the M4A as needs_pc so the Audio Hören copy carries
# the correct fallback state. Only clean, non-empty output is recognized_complete.
old_meta = '            _ = try updateSpeechMetadata(for: sourceURL, status: "recognized_complete", reason: warnings.isEmpty ? nil : warnings.joined(separator: " | "), whisperConfidence: whisperConfidence, whisperScoredTokens: whisperScoredTokens, normalizerVersion: normalizerVersion)\n'
new_meta = '''            let cleanTextForRouting = text.trimmingCharacters(in: .whitespacesAndNewlines)\n            let hasProcessingProblem = !warnings.isEmpty || cleanTextForRouting.isEmpty\n            let routingReason: String? = !warnings.isEmpty\n                ? warnings.joined(separator: " | ")\n                : (cleanTextForRouting.isEmpty ? "Результат распознавания пустой" : nil)\n            _ = try updateSpeechMetadata(\n                for: sourceURL,\n                status: hasProcessingProblem ? "needs_pc" : "recognized_complete",\n                reason: routingReason,\n                whisperConfidence: whisperConfidence,\n                whisperScoredTokens: whisperScoredTokens,\n                normalizerVersion: normalizerVersion\n            )\n'''
if old_meta not in p:
    raise SystemExit('finishSuccess metadata marker not found')
p = p.replace(old_meta, new_meta, 1)

old = '''            var queue = loadQueue(); queue.removeAll { $0.id == item.id }; saveQueue(queue)\n            stopFileDeadline()\n            activeItemID = nil\n            setProcessingLocked(false)\n            DispatchQueue.main.async {\n                self.lastResult = result\n                self.lastError = warnings.isEmpty ? nil : warnings.joined(separator: " | ")\n                if text.isEmpty {\n                    self.statusText = "Готово · речь не найдена"\n                } else if warnings.isEmpty {\n                    self.statusText = "Готово"\n                } else {\n                    self.statusText = "Готово · с предупреждением"\n                }\n                self.onStateChanged?()\n                self.onAudioReady?(sourceURL)\n                self.onJournalUpdated?(transcriptFile)\n            }\n            try? fm.removeItem(at: speechTempDirectory)\n            processNextLocked()\n'''
new = '''            var queue = loadQueue(); queue.removeAll { $0.id == item.id }; saveQueue(queue)\n            stopFileDeadline()\n            activeItemID = nil\n            setProcessingLocked(false)\n\n            let shouldDeleteSourceAudio = !hasProcessingProblem\n\n            DispatchQueue.main.async {\n                self.lastResult = result\n                self.lastError = warnings.isEmpty ? nil : warnings.joined(separator: " | ")\n                if cleanTextForRouting.isEmpty {\n                    self.statusText = "Audio Hören · пустой результат"\n                } else if warnings.isEmpty {\n                    self.statusText = "Готово"\n                } else {\n                    self.statusText = "Audio Hören · предупреждение"\n                }\n                self.onStateChanged?()\n                self.onJournalUpdated?(transcriptFile)\n                if hasProcessingProblem {\n                    self.onAudioReady?(sourceURL)\n                }\n            }\n\n            // Clean + non-empty + no warnings: TXT is the durable result, so delete M4A.\n            // Any warning or empty result: keep M4A and queue it to Google Drive Audio Hören.\n            if shouldDeleteSourceAudio {\n                try fm.removeItem(at: sourceURL)\n                let sidecar = sourceURL.deletingPathExtension().appendingPathExtension("meta.json")\n                try? fm.removeItem(at: sidecar)\n            }\n\n            try? fm.removeItem(at: speechTempDirectory)\n            processNextLocked()\n'''
if old not in p:
    raise SystemExit('finishSuccess completion block not found')
p = p.replace(old, new, 1)

for required in (
    'let hasProcessingProblem = !warnings.isEmpty || cleanTextForRouting.isEmpty',
    'status: hasProcessingProblem ? "needs_pc" : "recognized_complete"',
    'self.onAudioReady?(sourceURL)',
    'markNeedsPC(item: item, sourceURL: sourceURL, reason: message, partialText: "")',
):
    if required not in p:
        raise SystemExit(f'routing invariant missing: {required}')
if 'warnings: [baseSummary]' in p or 'let baseSummary =' in p:
    raise SystemExit('Base score still misclassified as warning')
processor.write_text(p)

# TXT must remain uploadable after a clean source M4A has been deleted locally.
d = drive.read_text()
old_gate = '''            do {\n                let inbox = try SharedTextPaths(fileManager: self.fm).audioInbox\n                let sourceM4A = inbox.appendingPathComponent(base).appendingPathExtension("m4a")\n                guard self.fm.fileExists(atPath: sourceM4A.path) else {\n                    self.setError("Audio Lesen: нет исходного M4A для \\(sourceURL.lastPathComponent)")\n                    return\n                }\n            } catch {\n                self.setError("Audio Lesen: \\(error.localizedDescription)")\n                return\n            }\n\n'''
if old_gate not in d:
    raise SystemExit('TXT source-M4A gate not found')
d = d.replace(old_gate, '', 1)
if 'нет исходного M4A' in d:
    raise SystemExit('source-M4A gate residue remains')
drive.write_text(d)

print('patched: clean audio deleted; error/warning/timeout/needs_pc/empty audio routed to Audio Hören')
