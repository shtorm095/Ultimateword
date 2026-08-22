from pathlib import Path
import subprocess

root = Path('/tmp/wmtext116-src')
proc = root/'WearMemoryText/TextProcessor.swift'
info = root/'WearMemoryText/Info.plist'

s = proc.read_text()

# Clear only the UI error when a NEW file actually starts processing.
# The previous file's error remains persisted in its .meta.json sidecar.
old_start = '''            setProcessingLocked(true)\n            activeItemID = item.id\n            _ = try? updateSpeechSidecar(for: sourceURL, status: "processing")\n            startFileDeadline(item: item, sourceURL: sourceURL)\n            publishStatus("Распознаю \\(item.sourceFileName) · лимит 3 мин")\n'''
new_start = '''            setProcessingLocked(true)\n            activeItemID = item.id\n            _ = try? updateSpeechSidecar(for: sourceURL, status: "processing")\n            clearDisplayedError()\n            startFileDeadline(item: item, sourceURL: sourceURL)\n            publishStatus("Распознаю \\(item.sourceFileName) · лимит 3 мин")\n'''
if old_start not in s:
    raise SystemExit('new-file processing block not found')
s = s.replace(old_start, new_start, 1)

old_publish = '''    private func publishPending(_ value: Int) { DispatchQueue.main.async { self.pendingCount = value; self.onStateChanged?() } }\n    private func publishStatus(_ value: String) { DispatchQueue.main.async { self.statusText = value; self.onStateChanged?() } }\n    private func publishError(_ value: String) { DispatchQueue.main.async { self.lastError = value; self.statusText = "Ошибка"; self.onStateChanged?() } }\n'''
new_publish = '''    private func publishPending(_ value: Int) { DispatchQueue.main.async { self.pendingCount = value; self.onStateChanged?() } }\n    private func clearDisplayedError() { DispatchQueue.main.async { self.lastError = nil; self.onStateChanged?() } }\n    private func publishStatus(_ value: String) { DispatchQueue.main.async { self.statusText = value; self.onStateChanged?() } }\n    private func publishError(_ value: String) { DispatchQueue.main.async { self.lastError = value; self.statusText = "Ошибка"; self.onStateChanged?() } }\n'''
if old_publish not in s:
    raise SystemExit('publish helper block not found')
s = s.replace(old_publish, new_publish, 1)

proc.write_text(s)

subprocess.run(['/usr/libexec/PlistBuddy','-c','Set :CFBundleShortVersionString 1.1.6',str(info)], check=True)
subprocess.run(['/usr/libexec/PlistBuddy','-c','Set :CFBundleVersion 16',str(info)], check=True)

print('patched v1.1.6: stale on-screen Speech errors are cleared at next-file start; metadata history is preserved')
