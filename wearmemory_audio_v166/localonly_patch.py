from pathlib import Path
import os

root = Path(os.environ.get('WM_AUDIO_ROOT', '/tmp/wm167' if Path('/tmp/wm167').exists() else '/tmp/wm166'))
appmodel = root / 'WearMemory/AppModel.swift'
project = root / 'project.yml'
info = root / 'WearMemory/Info.plist'

s = appmodel.read_text()

# Audio app becomes a recorder/handoff app. Text recognition is handled by WearMemory Text.
s = s.replace('@Published var transcriptionEnabled = true {', '@Published var transcriptionEnabled = false {')

old = '''        logs.onTextFileUpdated = { [weak self] url in
            self?.driveSync.enqueueText(url)
        }
        transcription.language = language
        transcription.onDeviceOnly = onDeviceOnly
        audio.transcribeSegments = transcriptionEnabled
        audio.onSegmentCompleted = { [weak self] url, _, _ in
            self?.driveSync.enqueueAudio(url)
        }
        audio.onSegmentReady = { [weak self] url, start, end in
            self?.logs.reloadIfDayChanged()
            self?.transcription.enqueue(url: url, startedAt: start, endedAt: end)
        }
'''
new = '''        // WearMemory Audio no longer uploads completed M4A files to Google Drive.
        // It only records and hands finalized files to WearMemory Text through the
        // shared App Group AudioInbox. WearMemory Text decides later whether a file
        // is fully recognized locally or needs PC processing.
        transcription.language = language
        transcription.onDeviceOnly = onDeviceOnly
        audio.transcribeSegments = false
        audio.onSegmentCompleted = { [weak self] url, start, end in
            self?.handoffAudioToText(url, startedAt: start, endedAt: end)
        }
        audio.onSegmentReady = nil
'''
if old not in s:
    raise SystemExit('AppModel callback block not found')
s = s.replace(old, new, 1)

insert_before = '''    deinit {
'''
helper = '''    private static let sharedGroupIdentifier = "group.local.pavel.WearMemory"

    private func handoffAudioToText(_ sourceURL: URL, startedAt: Date, endedAt: Date) {
        let fm = FileManager.default
        guard let root = fm.containerURL(forSecurityApplicationGroupIdentifier: Self.sharedGroupIdentifier) else {
            return
        }

        do {
            let inbox = root.appendingPathComponent("AudioInbox", isDirectory: true)
            try fm.createDirectory(at: inbox, withIntermediateDirectories: true)

            // Copy to a temporary name first. WearMemory Text only sees a final .m4a
            // after the copy has completed, so it can never read a half-written file.
            let finalURL = inbox.appendingPathComponent(sourceURL.lastPathComponent)
            let tempURL = inbox.appendingPathComponent(sourceURL.lastPathComponent + ".part")
            try? fm.removeItem(at: tempURL)
            if fm.fileExists(atPath: finalURL.path) {
                try fm.removeItem(at: finalURL)
            }
            try fm.copyItem(at: sourceURL, to: tempURL)
            try fm.moveItem(at: tempURL, to: finalURL)

            let iso = ISO8601DateFormatter()
            let metadata: [String: Any] = [
                "bridgeVersion": 2,
                "sourceFileName": sourceURL.lastPathComponent,
                "startedAt": iso.string(from: startedAt),
                "endedAt": iso.string(from: endedAt),
                "exportedAt": iso.string(from: Date()),
                "speechStatus": "pending_ipod"
            ]
            let data = try JSONSerialization.data(withJSONObject: metadata, options: [.prettyPrinted, .sortedKeys])
            let stem = sourceURL.deletingPathExtension().lastPathComponent
            let metaFinal = inbox.appendingPathComponent(stem + ".meta.json")
            let metaTemp = inbox.appendingPathComponent(stem + ".meta.json.part")
            try? fm.removeItem(at: metaTemp)
            try data.write(to: metaTemp, options: .atomic)
            if fm.fileExists(atPath: metaFinal.path) {
                try fm.removeItem(at: metaFinal)
            }
            try fm.moveItem(at: metaTemp, to: metaFinal)
        } catch {
            // Keep the original AudioBuffer file intact. A failed handoff must never
            // destroy the recording; the next release can expose/retry such failures.
        }
    }

'''
if insert_before not in s:
    raise SystemExit('AppModel insertion point not found')
s = s.replace(insert_before, helper + insert_before, 1)
appmodel.write_text(s)

# Add the same App Group entitlement used by WearMemory Text.
entitlements = root / 'WearMemory/WearMemory.entitlements'
entitlements.write_text('''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>application-identifier</key><string>TROLLTROLL.*</string>
    <key>com.apple.developer.team-identifier</key><string>TROLLTROLL</string>
    <key>get-task-allow</key><true/>
    <key>keychain-access-groups</key>
    <array><string>TROLLTROLL.*</string><string>com.apple.token</string></array>
    <key>com.apple.security.application-groups</key>
    <array><string>group.local.pavel.WearMemory</string></array>
</dict>
</plist>
''')

p = project.read_text()
needle = "        CODE_SIGN_STYLE: Automatic\n"
replacement = "        CODE_SIGN_STYLE: Automatic\n        CODE_SIGN_ENTITLEMENTS: WearMemory/WearMemory.entitlements\n"
if needle not in p:
    raise SystemExit('project.yml signing block not found')
p = p.replace(needle, replacement, 1)
project.write_text(p)

# Version 1.6.6 build 24.
import subprocess
subprocess.run(['/usr/libexec/PlistBuddy', '-c', 'Set :CFBundleShortVersionString 1.6.6', str(info)], check=True)
subprocess.run(['/usr/libexec/PlistBuddy', '-c', 'Set :CFBundleVersion 24', str(info)], check=True)
