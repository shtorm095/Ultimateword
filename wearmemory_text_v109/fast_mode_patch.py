from pathlib import Path

p = Path('WearMemoryText/TextProcessor.swift')
s = p.read_text()

replacements = [
    ('let primaryOverlap = 5.0', 'let primaryOverlap = 2.0'),
    ('let overlap = 3.0', 'let overlap = 2.0'),
    ('let useOnDevice = forceOnDevice ?? canOnDevice', 'let useOnDevice = forceOnDevice ?? false'),
    ('self.workQueue.asyncAfter(deadline: .now() + 0.9) {', 'self.workQueue.asyncAfter(deadline: .now() + 0.25) {'),
    ('if retryable && attempt < 3 {', 'if retryable && attempt < 1 {'),
    ('self.workQueue.asyncAfter(deadline: .now() + min(4.0, Double(attempt + 1) * 1.25)) {', 'self.workQueue.asyncAfter(deadline: .now() + 0.35) {'),
]
for old, new in replacements:
    if old not in s:
        raise SystemExit(f'pattern not found: {old}')
    s = s.replace(old, new, 1)

# Status text makes it visible that the fast path is server-first.
s = s.replace('(usingOnDevice ? " · локально" : " · сервер") +', '(usingOnDevice ? " · локально" : " · сервер FAST") +', 1)

p.write_text(s)
