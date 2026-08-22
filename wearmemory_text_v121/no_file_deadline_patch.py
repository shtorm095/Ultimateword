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

# The old 3-minute whole-file watchdog is too short for Base -> Small full-file dual pass.
# Keep the safety watchdog, but extend it to 9 minutes (540 seconds).
old = '    private let maxFileProcessingSeconds: TimeInterval = 180\n'
new = '    private let maxFileProcessingSeconds: TimeInterval = 540\n'
if old not in p:
    raise SystemExit('180-second file deadline not found')
p = p.replace(old, new, 1)

old = '            publishStatus("Распознаю \\(item.sourceFileName) · лимит 3 мин")\n'
new = '            publishStatus("Распознаю \\(item.sourceFileName) · лимит 9 мин")\n'
if old not in p:
    raise SystemExit('3-minute processing status not found')
p = p.replace(old, new, 1)

old = 'Общий лимит обработки на iPod: 3 минуты'
new = 'Общий лимит обработки на iPod: 9 минут'
if old not in p:
    raise SystemExit('3-minute deadline error text not found')
p = p.replace(old, new, 1)

if 'maxFileProcessingSeconds: TimeInterval = 180' in p:
    raise SystemExit('180-second deadline residue remains')
if 'лимит 3 мин' in p or '3 минуты' in p:
    raise SystemExit('3-minute deadline text residue remains in TextProcessor.swift')
if 'maxFileProcessingSeconds: TimeInterval = 540' not in p:
    raise SystemExit('540-second deadline missing')
processor.write_text(p)

c = content.read_text()
old = '                info("timer", "Лимит файла", "3 минуты", .cyan)\n'
new = '                info("timer", "Лимит файла", "9 минут", .cyan)\n'
if old not in c:
    raise SystemExit('3-minute UI row not found')
c = c.replace(old, new, 1)
if 'Лимит файла", "9 минут"' not in c:
    raise SystemExit('9-minute UI row missing')
content.write_text(c)

with info.open('rb') as f:
    plist = plistlib.load(f)
plist['CFBundleShortVersionString'] = '1.2.6'
plist['CFBundleVersion'] = '26'
with info.open('wb') as f:
    plistlib.dump(plist, f, fmt=plistlib.FMT_XML, sort_keys=False)

print('patched WearMemory Text 1.2.6: file watchdog extended from 3 to 9 minutes')
