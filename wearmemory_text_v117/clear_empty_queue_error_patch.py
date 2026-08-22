from pathlib import Path
import subprocess

root = Path('/tmp/wmtext117-src')
proc = root/'WearMemoryText/TextProcessor.swift'
info = root/'WearMemoryText/Info.plist'

s = proc.read_text()

# When the processor reaches an empty queue there is no active file anymore.
# Clear only the transient UI error. The previous file's detailed error stays
# persisted in its .meta.json (ipadStatus/ipadErrorMessage/ipadErrorAt).
old_empty = '''        var queue = loadQueue()\n        guard !queue.isEmpty else {\n            publishStatus("Очередь пуста")\n            return\n        }\n'''
new_empty = '''        var queue = loadQueue()\n        guard !queue.isEmpty else {\n            clearDisplayedError()\n            publishStatus("Очередь пуста")\n            return\n        }\n'''
if old_empty not in s:
    raise SystemExit('empty-queue block not found')
s = s.replace(old_empty, new_empty, 1)

proc.write_text(s)

subprocess.run(['/usr/libexec/PlistBuddy','-c','Set :CFBundleShortVersionString 1.1.7',str(info)], check=True)
subprocess.run(['/usr/libexec/PlistBuddy','-c','Set :CFBundleVersion 17',str(info)], check=True)

print('patched v1.1.7: stale on-screen Speech error clears when queue becomes empty')
