from pathlib import Path
import re

source = Path(__file__).with_name("whisper_production_patch_original.py")
code = source.read_text()
pattern = re.compile(
    r"start_marker = .*?\nstart = t\.find\(start_marker\)\nif start < 0:\n    raise SystemExit\('process recognition start marker not found'\)\n",
    re.S,
)
replacement = """start = t.find('            splitIntoPieces(sourceURL)')
if start < 0:
    raise SystemExit('process recognition start marker not found')
"""
code, count = pattern.subn(lambda _: replacement, code, count=1)
if count != 1:
    raise SystemExit(f'expected one start-marker block, found {count}')
exec(compile(code, str(source), 'exec'), {'__file__': str(source), '__name__': '__main__'})
