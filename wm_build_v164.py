from pathlib import Path
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/wm164")


def replace_func(text: str, signature: str, replacement: str) -> str:
    start = text.find(signature)
    if start < 0:
        raise RuntimeError(f"function not found: {signature}")
    brace = text.find("{", start)
    if brace < 0:
        raise RuntimeError(f"opening brace not found: {signature}")
    depth = 0
    for i in range(brace, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[:start] + replacement + text[i + 1 :]
    raise RuntimeError(f"unbalanced function: {signature}")


# Keep the v1.6.1 recording-state propagation so the button changes blue/red immediately.
p = root / "WearMemory/AppModel.swift"
s = p.read_text()
if "import Combine" not in s:
    s = s.replace("import UIKit\n", "import UIKit\nimport Combine\n", 1)
marker = "    private var batteryObserver: NSObjectProtocol?\n"
if marker not in s:
    raise RuntimeError("AppModel batteryObserver marker missing")
if "private var cancellables = Set<AnyCancellable>()" not in s:
    s = s.replace(marker, marker + "    private var cancellables = Set<AnyCancellable>()\n", 1)
if "audio.objectWillChange" not in s:
    init_marker = "    init() {\n"
    if init_marker not in s:
        raise RuntimeError("AppModel init marker missing")
    s = s.replace(
        init_marker,
        """    init() {\n        audio.objectWillChange\n            .receive(on: DispatchQueue.main)\n            .sink { [weak self] _ in self?.objectWillChange.send() }\n            .store(in: &cancellables)\n\n""",
        1,
    )
p.write_text(s)


p = root / "WearMemory/GoogleDriveSync.swift"
s = p.read_text()

# Finalized audio must be copied to the durable pending directory and queue before upload.
s = replace_func(
    s,
    "    func enqueueAudio(_ sourceURL: URL)",
    r'''    func enqueueAudio(_ sourceURL: URL) {
        guard syncEnabled else { return }
        workQueue.sync {
            guard self.fm.fileExists(atPath: sourceURL.path) else {
                self.setError("Очередь Google Drive: завершённый аудиофайл не найден")
                return
            }
            let size = (try? sourceURL.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
            guard size > 0 else {
                self.setError("Очередь Google Drive: завершённый аудиофайл пуст")
                return
            }
            let target = self.pendingAudioDirectory.appendingPathComponent(sourceURL.lastPathComponent)
            do {
                if self.fm.fileExists(atPath: target.path) {
                    try self.fm.removeItem(at: target)
                }
                try self.fm.copyItem(at: sourceURL, to: target)
            } catch {
                self.setError("Очередь Google Drive: \(error.localizedDescription)")
                return
            }
            var queue = self.loadQueue()
            let id = "audio:\(target.lastPathComponent)"
            queue.removeAll { $0.id == id }
            queue.append(PendingItem(id: id, kind: .audio, path: target.path))
            self.saveQueue(queue)
            self.flushQueueLocked()
        }
    }''',
)

# Insert helpers once.
if "private func reconcilePendingAudioFilesLocked()" not in s:
    pos = s.find("    private func flushQueueLocked()")
    if pos < 0:
        raise RuntimeError("flushQueueLocked marker missing")
    helpers = r'''    private func reconcilePendingAudioFilesLocked() {
        guard let files = try? fm.contentsOfDirectory(
            at: pendingAudioDirectory,
            includingPropertiesForKeys: [.fileSizeKey],
            options: [.skipsHiddenFiles]
        ) else { return }
        var queue = loadQueue()
        var changed = false
        for url in files where url.pathExtension.lowercased() == "m4a" {
            let size = (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
            guard size > 0 else { continue }
            let id = "audio:\(url.lastPathComponent)"
            if !queue.contains(where: { $0.id == id }) {
                queue.append(PendingItem(id: id, kind: .audio, path: url.path))
                changed = true
            }
        }
        if changed { saveQueue(queue) }
    }

    private func publishHealthyStatus() {
        let count = loadQueue().count
        DispatchQueue.main.async {
            self.pendingCount = count
            self.lastError = nil
            self.updatePublishedStatus()
        }
    }

    private func isRetryableNetworkError(_ error: Error) -> Bool {
        let ns = error as NSError
        guard ns.domain == NSURLErrorDomain else { return false }
        return [
            NSURLErrorNetworkConnectionLost,
            NSURLErrorNotConnectedToInternet,
            NSURLErrorTimedOut,
            NSURLErrorCannotConnectToHost,
            NSURLErrorDNSLookupFailed,
            NSURLErrorCannotFindHost
        ].contains(ns.code)
    }

    private func scheduleQueueRetry(after delay: TimeInterval = 5) {
        workQueue.asyncAfter(deadline: .now() + delay) { [weak self] in
            guard let self = self, !self.isFlushing else { return }
            self.flushQueueLocked()
        }
    }

'''
    s = s[:pos] + helpers + s[pos:]

s = replace_func(
    s,
    "    private func flushQueueLocked()",
    r'''    private func flushQueueLocked() {
        guard syncEnabled, isAuthorized, foldersAuthorized, !isFlushing else { return }
        reconcilePendingAudioFilesLocked()
        let queue = loadQueue()
        guard !queue.isEmpty else {
            updatePendingCount()
            publishHealthyStatus()
            return
        }
        isFlushing = true
        process(queue: queue, index: 0)
    }''',
)

s = replace_func(
    s,
    "    private func process(queue: [PendingItem], index: Int)",
    r'''    private func process(queue: [PendingItem], index: Int) {
        if index >= queue.count {
            isFlushing = false
            updatePendingCount()
            publishHealthyStatus()
            return
        }
        let item = queue[index]
        let url = URL(fileURLWithPath: item.path)
        guard fm.fileExists(atPath: url.path) else {
            removePending(id: item.id)
            process(queue: loadQueue(), index: 0)
            return
        }

        withAccessToken { [weak self] tokenResult in
            guard let self = self else { return }
            switch tokenResult {
            case .failure(let error):
                self.workQueue.async {
                    self.isFlushing = false
                    self.setError("Google Drive: \(error.localizedDescription)")
                    if self.isRetryableNetworkError(error) {
                        self.scheduleQueueRetry()
                    }
                }
            case .success(let token):
                self.upload(item: item, url: url, accessToken: token) { result in
                    self.workQueue.async {
                        switch result {
                        case .failure(let error):
                            self.isFlushing = false
                            self.setError("Google Drive: \(error.localizedDescription)")
                            if self.isRetryableNetworkError(error) {
                                self.scheduleQueueRetry()
                            }
                        case .success:
                            self.removePending(id: item.id)
                            if item.kind == .audio {
                                try? self.fm.removeItem(at: url)
                            }
                            self.publishHealthyStatus()
                            self.process(queue: self.loadQueue(), index: 0)
                        }
                    }
                }
            }
        }
    }''',
)

# URLSessionUploadTask is used for request bodies, including binary M4A multipart data.
old_create = "        request.httpBody = body\n        URLSession.shared.dataTask(with: request) { data, response, error in"
if old_create in s:
    s = s.replace(
        old_create,
        "        URLSession.shared.uploadTask(with: request, from: body) { data, response, error in",
        1,
    )
elif "URLSession.shared.uploadTask(with: request, from: body)" not in s:
    raise RuntimeError("createFile request-body pattern missing")

old_update = "        request.httpBody = data\n        URLSession.shared.dataTask(with: request) { data, response, error in"
if old_update in s:
    s = s.replace(
        old_update,
        "        URLSession.shared.uploadTask(with: request, from: data) { data, response, error in",
        1,
    )
elif "URLSession.shared.uploadTask(with: request, from: data)" not in s:
    raise RuntimeError("updateFile request-body pattern missing")

p.write_text(s)

# Version.
p = root / "WearMemory/Info.plist"
s = p.read_text()
import re
s = re.sub(r"(<key>CFBundleShortVersionString</key>\s*<string>)[^<]+(</string>)", r"\g<1>1.6.4\2", s, count=1)
s = re.sub(r"(<key>CFBundleVersion</key>\s*<string>)[^<]+(</string>)", r"\g<1>22\2", s, count=1)
p.write_text(s)

# Ensure XcodeGen uses the maintained Info.plist.
p = root / "project.yml"
s = p.read_text()
old = "    info:\n      path: WearMemory/Info.plist\n"
marker = "        PRODUCT_NAME: WearMemory\n"
if marker not in s:
    raise RuntimeError("project.yml PRODUCT_NAME marker missing")
if old in s:
    s = s.replace(old, "", 1)
if "INFOPLIST_FILE: WearMemory/Info.plist" not in s:
    s = s.replace(marker, marker + "        INFOPLIST_FILE: WearMemory/Info.plist\n", 1)
p.write_text(s)

print("WearMemory v1.6.4 Drive patch applied")
