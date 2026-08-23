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
old = '    private let maxFileProcessingSeconds: TimeInterval = 180\n'
new = '    private let maxFileProcessingSeconds: TimeInterval = 540\n'
if old not in p:
    raise SystemExit('3-minute processing limit not found')
p = p.replace(old, new, 1)

old = '                self.markNeedsPC(item: item, sourceURL: sourceURL, reason: "Общий лимит обработки на iPod: 3 минуты", partialText: "")\n'
new = '                self.markNeedsPC(item: item, sourceURL: sourceURL, reason: "Общий лимит обработки на iPod: 9 минут", partialText: "")\n'
if old not in p:
    raise SystemExit('3-minute deadline error text not found')
p = p.replace(old, new, 1)

old = '            publishStatus("Распознаю \\(item.sourceFileName) · лимит 3 мин")\n'
new = '            publishStatus("Распознаю \\(item.sourceFileName) · лимит 9 мин")\n'
if old not in p:
    raise SystemExit('3-minute processing status not found')
p = p.replace(old, new, 1)

if 'maxFileProcessingSeconds: TimeInterval = 180' in p or 'лимит 3 мин' in p or '3 минуты' in p:
    raise SystemExit('3-minute watchdog residue remains in TextProcessor.swift')
processor.write_text(p)

c = content.read_text()
old = '                info("timer", "Лимит файла", "3 минуты", .cyan)\n'
new = '                info("timer", "Лимит файла", "9 минут", .cyan)\n'
if old not in c:
    raise SystemExit('3-minute UI row not found')
c = c.replace(old, new, 1)
if 'Лимит файла", "3 минуты' in c:
    raise SystemExit('3-minute UI residue remains')
content.write_text(c)

with info.open('rb') as f:
    plist = plistlib.load(f)
plist['CFBundleShortVersionString'] = '1.2.6'
plist['CFBundleVersion'] = '26'
with info.open('wb') as f:
    plistlib.dump(plist, f, fmt=plistlib.FMT_XML, sort_keys=False)

print('patched WearMemory Text 1.2.6: whole-file watchdog extended to 9 minutes')
