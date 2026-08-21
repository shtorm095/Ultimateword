from pathlib import Path

p = Path('WearMemoryText/TextProcessor.swift')
s = p.read_text()

old_partial = '''                    has("kAFAssistantErrorDomain", 203) ||
                    has("SiriSpeechErrorDomain", 1) ||
                    has("kAFAssistantErrorDomain", 1101) ||
'''
new_partial = '''                    has("kAFAssistantErrorDomain", 203) ||
                    has("SiriSpeechErrorDomain", 1) ||
                    has("SiriSpeechErrorDomain", 101) ||
                    has("SiriSpeechErrorDomain", 102) ||
                    has("kAFAssistantErrorDomain", 1101) ||
'''
if old_partial not in s:
    raise SystemExit('partial-result error block not found')
s = s.replace(old_partial, new_partial, 1)

old_retry = '''                    has("kAFAssistantErrorDomain", 203) ||
                    has("SiriSpeechErrorDomain", 1) ||
                    has("kAFAssistantErrorDomain", 33) ||
'''
new_retry = '''                    has("kAFAssistantErrorDomain", 203) ||
                    has("SiriSpeechErrorDomain", 1) ||
                    has("SiriSpeechErrorDomain", 101) ||
                    has("SiriSpeechErrorDomain", 102) ||
                    has("kAFAssistantErrorDomain", 33) ||
'''
if old_retry not in s:
    raise SystemExit('retryable error block not found')
s = s.replace(old_retry, new_retry, 1)

p.write_text(s)
