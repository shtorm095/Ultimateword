from pathlib import Path
import plistlib

root = Path('/tmp/wmtext121-src/WearMemoryText')
processor = root / 'TextProcessor.swift'
content = root / 'ContentView.swift'
info = root / 'Info.plist'

for path in (processor, content, info):
    if not path.exists():
        raise SystemExit(f'missing {path}')

p = processor.read_text()

# Remove the obsolete whole-file 3-minute watchdog. It predates the current
# Base -> Small full-file dual pass and can abort a healthy local Whisper job.
for old in (
    '    private var fileDeadlineWorkItem: DispatchWorkItem?\n',
    '    private let maxFileProcessingSeconds: TimeInterval = 180\n',
):
    if old not in p:
        raise SystemExit(f'expected deadline property not found: {old!r}')
    p = p.replace(old, '', 1)

old_deinit = '    deinit { currentTask?.cancel(); currentTask = nil; currentRecognizer = nil; currentRequest = nil; retryWorkItem?.cancel(); fileDeadlineWorkItem?.cancel() }\n'
new_deinit = '    deinit { currentTask?.cancel(); currentTask = nil; currentRecognizer = nil; currentRequest = nil; retryWorkItem?.cancel() }\n'
if old_deinit not in p:
    raise SystemExit('deadline deinit marker not found')
p = p.replace(old_deinit, new_deinit, 1)

for old in (
    '            startFileDeadline(item: item, sourceURL: sourceURL)\n',
    '            publishStatus("Распознаю \\(item.sourceFileName) · лимит 3 мин")\n',
):
    if old not in p:
        raise SystemExit(f'processing deadline marker not found: {old!r}')
    p = p.replace(old, '', 1)

start = p.find('    private func startFileDeadline(item: TextQueueItem, sourceURL: URL) {')
end_marker = '    private let wearMemoryMetadataPrefix = "WEARMEMORY_META_V1:"\n'
end = p.find(end_marker, start)
if start < 0 or end < 0:
    raise SystemExit('deadline function block not found')
p = p[:start] + end_marker + p[end + len(end_marker):]

# Terminal paths no longer need to cancel a file deadline.
p = p.replace('        stopFileDeadline()\n', '')

for forbidden in (
    'maxFileProcessingSeconds',
    'fileDeadlineWorkItem',
    'startFileDeadline(',
    'stopFileDeadline()',
    'Общий лимит обработки на iPod: 3 минуты',
    'лимит 3 мин',
):
    if forbidden in p:
        raise SystemExit(f'deadline residue remains in TextProcessor.swift: {forbidden}')
processor.write_text(p)

c = content.read_text()
ui_line = '                info("timer", "Лимит файла", "3 минуты", .cyan)\n'
if ui_line not in c:
    raise SystemExit('3-minute UI row not found')
c = c.replace(ui_line, '', 1)
if 'Лимит файла' in c or '3 минуты' in c:
    raise SystemExit('3-minute UI residue remains')
content.write_text(c)

with info.open('rb') as f:
    plist = plistlib.load(f)
plist['CFBundleShortVersionString'] = '1.2.6'
plist['CFBundleVersion'] = '26'
with info.open('wb') as f:
    plistlib.dump(plist, f, fmt=plistlib.FMT_XML, sort_keys=False)

print('patched WearMemory Text 1.2.6: removed obsolete 3-minute whole-file deadline')
