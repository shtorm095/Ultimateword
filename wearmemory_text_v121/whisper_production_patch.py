from pathlib import Path

source = Path(__file__).with_name("whisper_production_patch_original.py")
code = source.read_text()
bad = r'\\\\(item.sourceFileName)'
good = r'\\(item.sourceFileName)'
if code.count(bad) != 1:
    raise SystemExit(f'expected exactly one bad marker, found {code.count(bad)}')
code = code.replace(bad, good, 1)
exec(compile(code, str(source), 'exec'), {'__file__': str(source), '__name__': '__main__'})
