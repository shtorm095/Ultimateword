from pathlib import Path

root = Path('/tmp/wm168')
audio = root/'WearMemory/AudioBufferManager.swift'
model = root/'WearMemory/AppModel.swift'

s = audio.read_text()
if 'var onManualRecordingStarted: (() -> Void)?' not in s:
    s = s.replace('''    var onSegmentReady: ((URL, Date, Date) -> Void)?\n    var onSegmentCompleted: ((URL, Date, Date) -> Void)?\n''','''    var onSegmentReady: ((URL, Date, Date) -> Void)?\n    var onSegmentCompleted: ((URL, Date, Date) -> Void)?\n    var onManualRecordingStarted: (() -> Void)?\n''',1)
if 'self.onManualRecordingStarted?()' not in s:
    s = s.replace('''                try self.configureSession()\n                try self.startNewSegment()\n''','''                try self.configureSession()\n                try self.startNewSegment()\n                self.onManualRecordingStarted?()\n''',1)
audio.write_text(s)

m = model.read_text()
if 'audio.onManualRecordingStarted' not in m:
    m = m.replace('''        audio.transcribeSegments = false\n''','''        audio.transcribeSegments = false\n        audio.onManualRecordingStarted = { [weak self] in\n            self?.publishBridgeStatus()\n            self?.openWearMemoryText()\n        }\n''',1)
if 'private func openWearMemoryText()' not in m:
    m = m.replace('''    private func publishBridgeStatus() {\n''','''    private func openWearMemoryText() {\n        guard let url = URL(string: "wearmemory-text://recording-started") else { return }\n        DispatchQueue.main.async {\n            UIApplication.shared.open(url, options: [:], completionHandler: nil)\n        }\n    }\n\n    private func publishBridgeStatus() {\n''',1)
model.write_text(m)
