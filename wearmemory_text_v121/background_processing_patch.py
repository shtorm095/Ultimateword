from pathlib import Path
import plistlib

root = Path('/tmp/wmtext121-src')
app = root / 'WearMemoryText'
app_model = app / 'TextAppModel.swift'
app_swift = app / 'WearMemoryTextApp.swift'
info = app / 'Info.plist'
keeper = app / 'BackgroundExecutionKeeper.swift'

for path in (app_model, app_swift, info):
    if not path.exists():
        raise SystemExit(f'missing {path}')

keeper.write_text(r'''import Foundation
import AVFoundation
import UIKit

/// Keeps the app in the iOS background-audio execution class only while
/// local Whisper recognition is actually running.
///
/// This is intended for the sideloaded/TrollStore build. It does not make
/// the process immune to iOS termination under memory/thermal pressure.
final class BackgroundExecutionKeeper {
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private let format = AVAudioFormat(standardFormatWithSampleRate: 44_100, channels: 1)!
    private var loopBuffer: AVAudioPCMBuffer?
    private var running = false
    private var backgroundTask: UIBackgroundTaskIdentifier = .invalid

    init() {
        engine.attach(player)
        engine.connect(player, to: engine.mainMixerNode, format: format)
        engine.mainMixerNode.outputVolume = 0.0
        loopBuffer = Self.makeSilentBuffer(format: format)
    }

    deinit {
        stop()
    }

    func start() {
        DispatchQueue.main.async { [weak self] in
            self?.startOnMain()
        }
    }

    func stop() {
        DispatchQueue.main.async { [weak self] in
            self?.stopOnMain()
        }
    }

    private func startOnMain() {
        guard !running else { return }
        guard let loopBuffer else { return }

        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playback, mode: .default, options: [.mixWithOthers])
            try session.setActive(true)

            if backgroundTask == .invalid {
                backgroundTask = UIApplication.shared.beginBackgroundTask(withName: "WearMemoryText.Whisper") { [weak self] in
                    self?.endBackgroundTaskOnly()
                }
            }

            engine.prepare()
            try engine.start()
            player.scheduleBuffer(loopBuffer, at: nil, options: [.loops], completionHandler: nil)
            player.play()
            running = true
        } catch {
            endBackgroundTaskOnly()
            running = false
        }
    }

    private func stopOnMain() {
        if player.isPlaying { player.stop() }
        if engine.isRunning { engine.stop() }
        running = false
        endBackgroundTaskOnly()
        try? AVAudioSession.sharedInstance().setActive(false, options: [.notifyOthersOnDeactivation])
    }

    private func endBackgroundTaskOnly() {
        guard backgroundTask != .invalid else { return }
        let task = backgroundTask
        backgroundTask = .invalid
        UIApplication.shared.endBackgroundTask(task)
    }

    private static func makeSilentBuffer(format: AVAudioFormat) -> AVAudioPCMBuffer? {
        let frames = AVAudioFrameCount(format.sampleRate)
        guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frames) else { return nil }
        buffer.frameLength = frames
        if let channels = buffer.floatChannelData {
            for channel in 0..<Int(format.channelCount) {
                for frame in 0..<Int(frames) {
                    channels[channel][frame] = 0.0
                }
            }
        }
        return buffer
    }
}
''')

m = app_model.read_text()
property_marker = '    let processor = TextProcessor()\n'
if property_marker not in m:
    raise SystemExit('TextAppModel processor marker not found')
m = m.replace(property_marker, property_marker + '    private let backgroundExecution = BackgroundExecutionKeeper()\n', 1)

init_marker = '''        for publisher in [processor.objectWillChange.eraseToAnyPublisher(), drive.objectWillChange.eraseToAnyPublisher()] {
            publisher.receive(on: DispatchQueue.main).sink { [weak self] _ in self?.objectWillChange.send() }.store(in: &cancellables)
        }
        refreshAll(autoProcess: false)
'''
if init_marker not in m:
    raise SystemExit('TextAppModel init publisher marker not found')
init_replacement = '''        for publisher in [processor.objectWillChange.eraseToAnyPublisher(), drive.objectWillChange.eraseToAnyPublisher()] {
            publisher.receive(on: DispatchQueue.main).sink { [weak self] _ in self?.objectWillChange.send() }.store(in: &cancellables)
        }

        // Start the background-audio keep-alive as soon as local Whisper starts,
        // while the app is still in the foreground. This avoids a race when the
        // user locks the screen or switches apps during recognition.
        processor.$isProcessing
            .removeDuplicates()
            .receive(on: DispatchQueue.main)
            .sink { [weak self] processing in
                if processing { self?.backgroundExecution.start() }
                else { self?.backgroundExecution.stop() }
            }
            .store(in: &cancellables)

        refreshAll(autoProcess: false)
'''
m = m.replace(init_marker, init_replacement, 1)
app_model.write_text(m)

s = app_swift.read_text()
old_scene = '''                .onChange(of: scenePhase) { phase in
                    if phase == .active { model.start() }
                    else if phase == .background { model.stopPolling() }
                }
'''
new_scene = '''                .onChange(of: scenePhase) { phase in
                    // Do not stop the queue poller on background entry. During an
                    // active Whisper job BackgroundExecutionKeeper keeps the process
                    // in the background-audio execution class so Base -> Small can
                    // continue with the screen locked or another app in front.
                    if phase == .active { model.start() }
                }
'''
if old_scene not in s:
    raise SystemExit('scenePhase background stop marker not found')
s = s.replace(old_scene, new_scene, 1)
app_swift.write_text(s)

with info.open('rb') as f:
    plist = plistlib.load(f)
modes = list(plist.get('UIBackgroundModes', []))
if 'audio' not in modes:
    modes.append('audio')
plist['UIBackgroundModes'] = modes
plist['CFBundleShortVersionString'] = '1.2.5'
plist['CFBundleVersion'] = '25'
with info.open('wb') as f:
    plistlib.dump(plist, f, fmt=plistlib.FMT_XML, sort_keys=False)

print('patched WearMemory Text 1.2.5: background Whisper keep-alive via iOS audio background mode')
