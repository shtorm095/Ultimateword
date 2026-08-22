from pathlib import Path
import subprocess

root = Path('/tmp/wmtext113-src')
drive = root/'WearMemoryText/TextDriveSync.swift'
model = root/'WearMemoryText/TextAppModel.swift'
content = root/'WearMemoryText/ContentView.swift'
info = root/'WearMemoryText/Info.plist'

# --- Google Drive belongs to Text, and Drive queue is serialized so needs_pc metadata
# is uploaded only after its M4A has completed. ---
s = drive.read_text()
s = s.replace('import Foundation\n', 'import Foundation\nimport CryptoKit\n', 1)
s = s.replace('''    static let clientID = "923188036776-mos9ub27f4k3bhnodr8r4n46flsisptj.apps.googleusercontent.com"\n''','''    static let clientID = "923188036776-mos9ub27f4k3bhnodr8r4n46flsisptj.apps.googleusercontent.com"\n    static let callbackScheme = "com.googleusercontent.apps.923188036776-mos9ub27f4k3bhnodr8r4n46flsisptj"\n    static let redirectURI = callbackScheme + ":/oauth2redirect"\n    static let scope = "https://www.googleapis.com/auth/drive.file"\n''',1)
s = s.replace('''    private let refreshTokenKey = "wearmemory.google.refresh_token"\n''','''    private let refreshTokenKey = "wearmemory.google.refresh_token"\n    private let pendingVerifierKey = "wearmemory.text.google.pending_pkce_verifier"\n    private let pendingStateKey = "wearmemory.text.google.pending_oauth_state"\n    private let pickedFoldersKey = "wearmemory.text.google.pickedFolders.v1"\n''',1)
s = s.replace('''    private var accessToken: String?\n    private var accessTokenExpiry: Date?\n''','''    private var accessToken: String?\n    private var accessTokenExpiry: Date?\n    private var currentVerifier: String?\n    private var currentState: String?\n''',1)

old_token = '''    private struct TokenResponse: Decodable {\n        let accessToken: String\n        let expiresIn: Int\n        enum CodingKeys: String, CodingKey {\n            case accessToken = "access_token"\n            case expiresIn = "expires_in"\n        }\n    }\n'''
new_token = '''    private struct TokenResponse: Decodable {\n        let accessToken: String\n        let expiresIn: Int\n        let refreshToken: String?\n        enum CodingKeys: String, CodingKey {\n            case accessToken = "access_token"\n            case expiresIn = "expires_in"\n            case refreshToken = "refresh_token"\n        }\n    }\n'''
if old_token not in s: raise SystemExit('TokenResponse block not found')
s = s.replace(old_token, new_token, 1)

start = s.index('    func refreshAuthorization() {\n')
end = s.index('    func enqueueText(_ sourceURL: URL) {\n', start)
new_auth = r'''    func refreshAuthorization() {
        workQueue.async { [weak self] in
            guard let self = self else { return }
            guard SharedGoogleKeychain.read(key: self.refreshTokenKey) != nil else {
                DispatchQueue.main.async {
                    self.isAuthorized = false
                    self.folderAuthorized = false
                    self.lastError = nil
                    self.updatePublishedStatus()
                }
                return
            }
            DispatchQueue.main.async {
                self.isAuthorized = true
                self.lastError = nil
                self.updatePublishedStatus()
            }
            self.verifyTargetFolders { verified in
                if verified && self.syncEnabled { self.flushQueue() }
            }
        }
    }

    func connect() {
        DispatchQueue.main.async {
            self.lastError = nil
            self.statusText = "Открываю Google в браузере…"
        }
        let verifier = Self.randomBase64URL(byteCount: 64)
        let challenge = Self.base64URL(Data(SHA256.hash(data: Data(verifier.utf8))))
        let state = Self.randomBase64URL(byteCount: 32)
        guard SharedGoogleKeychain.write(key: pendingVerifierKey, value: verifier),
              SharedGoogleKeychain.write(key: pendingStateKey, value: state) else {
            clearPendingOAuth()
            setError("Не удалось сохранить временные данные OAuth")
            return
        }
        currentVerifier = verifier
        currentState = state

        var components = URLComponents(string: "https://accounts.google.com/o/oauth2/v2/auth")!
        components.queryItems = [
            URLQueryItem(name: "client_id", value: Self.clientID),
            URLQueryItem(name: "scope", value: Self.scope),
            URLQueryItem(name: "redirect_uri", value: Self.redirectURI),
            URLQueryItem(name: "response_type", value: "code"),
            URLQueryItem(name: "access_type", value: "offline"),
            URLQueryItem(name: "prompt", value: "consent"),
            URLQueryItem(name: "trigger_onepick", value: "true"),
            URLQueryItem(name: "allow_multiple", value: "true"),
            URLQueryItem(name: "allow_folder_selection", value: "true"),
            URLQueryItem(name: "mimetypes", value: "application/vnd.google-apps.folder"),
            URLQueryItem(name: "file_ids", value: [Self.textFolderID, Self.audioFolderID].joined(separator: ",")),
            URLQueryItem(name: "code_challenge", value: challenge),
            URLQueryItem(name: "code_challenge_method", value: "S256"),
            URLQueryItem(name: "state", value: state)
        ]
        guard let url = components.url else {
            clearPendingOAuth()
            setError("Не удалось создать URL авторизации")
            return
        }
        DispatchQueue.main.async {
            UIApplication.shared.open(url, options: [:]) { [weak self] success in
                if !success {
                    self?.clearPendingOAuth()
                    self?.setError("Не удалось открыть браузер для Google OAuth")
                }
            }
        }
    }

    @discardableResult
    func handleOpenURL(_ url: URL) -> Bool {
        guard url.scheme == Self.callbackScheme else { return false }
        handleOAuthCallback(url)
        return true
    }

    func disconnect() {
        clearPendingOAuth()
        accessToken = nil
        accessTokenExpiry = nil
        SharedGoogleKeychain.delete(key: refreshTokenKey)
        defaults.removeObject(forKey: pickedFoldersKey)
        DispatchQueue.main.async {
            self.isAuthorized = false
            self.folderAuthorized = false
            self.lastError = nil
            self.updatePublishedStatus()
        }
    }

'''
s = s[:start] + new_auth + s[end:]

# Replace single-folder verification with verification of both fixed destinations.
start = s.index('    private func verifyTextFolder(completion: @escaping (Bool) -> Void) {\n')
end = s.index('    private func flushQueueLocked() {\n', start)
verify = r'''    private func verifyTargetFolders(completion: @escaping (Bool) -> Void) {
        withAccessToken { [weak self] result in
            guard let self = self else { return }
            switch result {
            case .failure(let error):
                DispatchQueue.main.async {
                    self.folderAuthorized = false
                    self.lastError = "Проверка папок: \(error.localizedDescription)"
                    self.updatePublishedStatus()
                    completion(false)
                }
            case .success(let token):
                let ids = [Self.textFolderID, Self.audioFolderID]
                let group = DispatchGroup()
                let lock = NSLock()
                var ok = true
                for id in ids {
                    group.enter()
                    var request = URLRequest(url: URL(string: "https://www.googleapis.com/drive/v3/files/\(id)?fields=id,name,mimeType")!)
                    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
                    URLSession.shared.dataTask(with: request) { _, response, _ in
                        let http = response as? HTTPURLResponse
                        let success = http.map { (200..<300).contains($0.statusCode) } ?? false
                        lock.lock(); if !success { ok = false }; lock.unlock()
                        group.leave()
                    }.resume()
                }
                group.notify(queue: self.workQueue) {
                    DispatchQueue.main.async {
                        self.folderAuthorized = ok
                        self.lastError = ok ? nil : "Нет доступа к папкам Audio Lesen / Audio Hören. Выберите обе папки."
                        self.updatePublishedStatus()
                        completion(ok)
                    }
                }
            }
        }
    }

'''
s = s[:start] + verify + s[end:]

# Serialize uploads. The queue order is M4A first, metadata second, so metadata becomes
# a reliable ready marker only after the complete M4A upload succeeds.
old_loop = '''                        let activeIDs = Set(tasks.compactMap { self.descriptor(for: $0)?.itemID })\n                        for item in self.loadQueue() where !activeIDs.contains(item.id) {\n                            do { try self.scheduleBackgroundUpload(item: item, accessToken: token) }\n                            catch { self.setError("Google Drive: \\(error.localizedDescription)") }\n                        }\n                        self.isFlushing = false\n                        self.updatePendingCount()\n'''
new_loop = '''                        let activeIDs = Set(tasks.compactMap { self.descriptor(for: $0)?.itemID })\n                        let queue = self.loadQueue()\n                        if activeIDs.isEmpty, let item = queue.first {\n                            do { try self.scheduleBackgroundUpload(item: item, accessToken: token) }\n                            catch { self.setError("Google Drive: \\(error.localizedDescription)") }\n                        }\n                        self.isFlushing = false\n                        self.updatePendingCount()\n'''
if old_loop not in s: raise SystemExit('upload scheduling loop not found')
s = s.replace(old_loop, new_loop, 1)

# needs_pc objects do not need a returned Drive ID. The previous code incorrectly treated
# M4A/JSON creates as text creates and kept them stuck in the queue when response data was empty.
old_id = '''        if descriptor.operation == .createText {\n            guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],\n                  let remoteID = json["id"] as? String else {\n                setError("Google Drive не вернул file id")\n                flushQueue(); return\n            }\n            defaults.set(remoteID, forKey: descriptor.mappingKey)\n        }\n'''
new_id = '''        if descriptor.operation == .createText && descriptor.itemID.hasPrefix("text:") {\n            guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],\n                  let remoteID = json["id"] as? String, !remoteID.isEmpty else {\n                setError("Google Drive не вернул file id для TXT")\n                flushQueue(); return\n            }\n            defaults.set(remoteID, forKey: descriptor.mappingKey)\n        }\n'''
if old_id not in s: raise SystemExit('file id block not found')
s = s.replace(old_id, new_id, 1)

# Insert OAuth callback/token helpers before withAccessToken.
marker = '    private func withAccessToken(_ completion: @escaping (Result<String, Error>) -> Void) {\n'
helpers = r'''    private func handleOAuthCallback(_ url: URL) {
        guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            clearPendingOAuth(); setError("Не удалось разобрать ответ Google"); return
        }
        let items = Dictionary(uniqueKeysWithValues: (components.queryItems ?? []).map { ($0.name, $0.value ?? "") })
        if let error = items["error"], !error.isEmpty {
            clearPendingOAuth(); setError("Google OAuth: \(error)"); return
        }
        let expectedState = currentState ?? SharedGoogleKeychain.read(key: pendingStateKey)
        let verifier = currentVerifier ?? SharedGoogleKeychain.read(key: pendingVerifierKey)
        if let returnedState = items["state"], !returnedState.isEmpty {
            guard let expectedState = expectedState, returnedState == expectedState else {
                clearPendingOAuth(); setError("OAuth state не совпадает"); return
            }
        }
        guard let code = items["code"], !code.isEmpty,
              let verifier = verifier, !verifier.isEmpty else {
            clearPendingOAuth(); setError("Google не вернул authorization code"); return
        }
        guard let rawPicked = items["picked_file_ids"], !rawPicked.isEmpty else {
            clearPendingOAuth(); setError("Google Picker не вернул выбранные папки"); return
        }
        let decoded = rawPicked.removingPercentEncoding ?? rawPicked
        let picked = decoded.split(separator: ",").map { String($0).trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
        let set = Set(picked)
        guard set.contains(Self.textFolderID), set.contains(Self.audioFolderID) else {
            clearPendingOAuth(); setError("Нужно выбрать обе папки: Audio Lesen и Audio Hören"); return
        }
        clearPendingOAuth()
        exchangeAuthorizationCode(code, verifier: verifier, pickedFolderIDs: picked)
    }

    private func exchangeAuthorizationCode(_ code: String, verifier: String, pickedFolderIDs: [String]) {
        DispatchQueue.main.async { self.statusText = "Получаю токен…" }
        tokenRequest(fields: [
            "code": code,
            "client_id": Self.clientID,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": Self.redirectURI
        ]) { [weak self] result in
            guard let self = self else { return }
            switch result {
            case .failure(let error): self.setError("Обмен OAuth-кода: \(error.localizedDescription)")
            case .success(let token):
                guard let refresh = token.refreshToken, !refresh.isEmpty else {
                    self.setError("Google не вернул refresh_token"); return
                }
                guard SharedGoogleKeychain.write(key: self.refreshTokenKey, value: refresh) else {
                    self.setError("Не удалось сохранить refresh_token в Keychain"); return
                }
                self.accessToken = token.accessToken
                self.accessTokenExpiry = Date().addingTimeInterval(TimeInterval(max(60, token.expiresIn - 60)))
                self.defaults.set(Array(Set(pickedFolderIDs)), forKey: self.pickedFoldersKey)
                DispatchQueue.main.async {
                    self.isAuthorized = true
                    self.statusText = "Проверяю доступ к папкам…"
                    self.updatePublishedStatus()
                }
                self.verifyTargetFolders { verified in if verified { self.flushQueue() } }
            }
        }
    }

    private func tokenRequest(fields: [String: String], completion: @escaping (Result<TokenResponse, Error>) -> Void) {
        var request = URLRequest(url: URL(string: "https://oauth2.googleapis.com/token")!)
        request.httpMethod = "POST"
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        request.httpBody = formEncoded(fields).data(using: .utf8)
        URLSession.shared.dataTask(with: request) { data, response, error in
            if let error = error { completion(.failure(error)); return }
            guard let http = response as? HTTPURLResponse, let data = data else {
                completion(.failure(self.driveError("Пустой ответ OAuth"))); return
            }
            guard (200..<300).contains(http.statusCode) else {
                let text = String(data: data, encoding: .utf8) ?? "HTTP \(http.statusCode)"
                completion(.failure(self.driveError(text))); return
            }
            do { completion(.success(try JSONDecoder().decode(TokenResponse.self, from: data))) }
            catch { completion(.failure(error)) }
        }.resume()
    }

    private func clearPendingOAuth() {
        currentVerifier = nil
        currentState = nil
        SharedGoogleKeychain.delete(key: pendingVerifierKey)
        SharedGoogleKeychain.delete(key: pendingStateKey)
    }

    private static func randomBase64URL(byteCount: Int) -> String {
        var bytes = [UInt8](repeating: 0, count: byteCount)
        let status = bytes.withUnsafeMutableBytes { raw in SecRandomCopyBytes(kSecRandomDefault, byteCount, raw.baseAddress!) }
        if status != errSecSuccess {
            return UUID().uuidString.replacingOccurrences(of: "-", with: "") + UUID().uuidString.replacingOccurrences(of: "-", with: "")
        }
        return base64URL(Data(bytes))
    }

    private static func base64URL(_ data: Data) -> String {
        data.base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
    }

'''
if marker not in s: raise SystemExit('withAccessToken marker not found')
s = s.replace(marker, helpers + marker, 1)

# Shared keychain now supports Text-owned OAuth writes and disconnect.
old_keychain_end = '''    static func read(key: String) -> String? {\n        let query: [String: Any] = [\n            kSecClass as String: kSecClassGenericPassword,\n            kSecAttrService as String: "local.pavel.WearMemory.GoogleDrive",\n            kSecAttrAccount as String: key,\n            kSecReturnData as String: true,\n            kSecMatchLimit as String: kSecMatchLimitOne\n        ]\n        var result: CFTypeRef?\n        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,\n              let data = result as? Data else { return nil }\n        return String(data: data, encoding: .utf8)\n    }\n}\n'''
new_keychain_end = '''    static func read(key: String) -> String? {\n        let query: [String: Any] = [\n            kSecClass as String: kSecClassGenericPassword,\n            kSecAttrService as String: "local.pavel.WearMemory.GoogleDrive",\n            kSecAttrAccount as String: key,\n            kSecReturnData as String: true,\n            kSecMatchLimit as String: kSecMatchLimitOne\n        ]\n        var result: CFTypeRef?\n        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,\n              let data = result as? Data else { return nil }\n        return String(data: data, encoding: .utf8)\n    }\n\n    static func write(key: String, value: String) -> Bool {\n        guard let data = value.data(using: .utf8) else { return false }\n        delete(key: key)\n        let query: [String: Any] = [\n            kSecClass as String: kSecClassGenericPassword,\n            kSecAttrService as String: "local.pavel.WearMemory.GoogleDrive",\n            kSecAttrAccount as String: key,\n            kSecValueData as String: data,\n            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly\n        ]\n        return SecItemAdd(query as CFDictionary, nil) == errSecSuccess\n    }\n\n    static func delete(key: String) {\n        let query: [String: Any] = [\n            kSecClass as String: kSecClassGenericPassword,\n            kSecAttrService as String: "local.pavel.WearMemory.GoogleDrive",\n            kSecAttrAccount as String: key\n        ]\n        SecItemDelete(query as CFDictionary)\n    }\n}\n'''
if old_keychain_end not in s: raise SystemExit('SharedGoogleKeychain block not found')
s = s.replace(old_keychain_end, new_keychain_end, 1)
drive.write_text(s)

# --- TextAppModel: Google callback belongs here; strict 24h retention before queue scan. ---
m = model.read_text()
m = m.replace('''    func handleURL(_ url: URL) {\n        guard url.scheme == "wearmemory-text" else { return }\n        refreshAll(autoProcess: true)\n    }\n''','''    func handleURL(_ url: URL) {\n        if drive.handleOpenURL(url) { return }\n        guard url.scheme == "wearmemory-text" else { return }\n        refreshAll(autoProcess: true)\n    }\n''',1)
m = m.replace('''    func refreshAll(autoProcess: Bool = true) {\n        refreshAppGroupAndAudioStatus()\n''','''    func refreshAll(autoProcess: Bool = true) {\n        purgeExpiredAudioInbox()\n        refreshAppGroupAndAudioStatus()\n''',1)
m = m.replace('''        timer = Timer.scheduledTimer(withTimeInterval: 4.0, repeats: true) { [weak self] _ in\n            self?.refreshAppGroupAndAudioStatus()\n''','''        timer = Timer.scheduledTimer(withTimeInterval: 4.0, repeats: true) { [weak self] _ in\n            self?.purgeExpiredAudioInbox()\n            self?.refreshAppGroupAndAudioStatus()\n''',1)
marker = '    private func refreshAppGroupAndAudioStatus() {\n'
purge = r'''    private func purgeExpiredAudioInbox() {
        guard let paths = try? SharedTextPaths(),
              let urls = try? FileManager.default.contentsOfDirectory(
                at: paths.audioInbox,
                includingPropertiesForKeys: [.contentModificationDateKey],
                options: [.skipsHiddenFiles]
              ) else { return }
        let now = Date()
        let iso = ISO8601DateFormatter()
        for url in urls where url.pathExtension.lowercased() == "m4a" {
            let meta = url.deletingPathExtension().appendingPathExtension("meta.json")
            var base: Date?
            if let data = try? Data(contentsOf: meta),
               let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let ended = object["endedAt"] as? String {
                base = iso.date(from: ended)
            }
            if base == nil {
                base = try? url.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate
            }
            guard let base = base, now.timeIntervalSince(base) >= 24 * 60 * 60 else { continue }
            try? FileManager.default.removeItem(at: url)
            try? FileManager.default.removeItem(at: meta)
        }
    }

'''
if marker not in m: raise SystemExit('app group marker not found')
m = m.replace(marker, purge + marker, 1)
model.write_text(m)

# --- UI: direct Drive ownership, playback route selection, playback mixed with recorder. ---
c = content.read_text()
if 'import AVFoundation\n' in c and 'import AVKit\n' not in c:
    c = c.replace('import AVFoundation\n', 'import AVFoundation\nimport AVKit\n', 1)
old_buttons = '''            HStack(spacing: 10) {\n                Button("Проверить доступ") { model.drive.refreshAuthorization() }\n                    .buttonStyle(.bordered)\n                if !model.drive.isAuthorized {\n                    Button("Подключить в Audio") {\n                        if let url = URL(string: "wearmemory-audio://open") { openURL(url) }\n                    }\n                    .buttonStyle(.borderedProminent)\n                }\n                Spacer()\n            }\n'''
new_buttons = '''            HStack(spacing: 10) {\n                Button("Проверить доступ") { model.drive.refreshAuthorization() }\n                    .buttonStyle(.bordered)\n                if model.drive.isAuthorized {\n                    Button("Отключить", role: .destructive) { model.drive.disconnect() }\n                        .buttonStyle(.bordered)\n                } else {\n                    Button("Подключить Google Drive") { model.drive.connect() }\n                        .buttonStyle(.borderedProminent)\n                }\n                Spacer()\n            }\n'''
if old_buttons not in c: raise SystemExit('drive UI buttons not found')
c = c.replace(old_buttons, new_buttons, 1)

old_route = '''            if let route = audioPlayer.outputRouteName {\n                VStack(spacing: 0) {\n                    info("headphones", "Аудиовыход", route, .cyan)\n                }\n                .padding(.vertical, 8)\n                .card()\n            }\n'''
new_route = '''            if let route = audioPlayer.outputRouteName {\n                VStack(spacing: 0) {\n                    info("headphones", "Аудиовыход", route, .cyan)\n                    Divider().background(Color.white.opacity(0.08))\n                    HStack {\n                        Text("Выбрать внешний аудиовыход").font(.subheadline)\n                        Spacer()\n                        TextAudioRoutePicker().frame(width: 48, height: 44)\n                    }\n                    .padding(.horizontal, 13)\n                }\n                .padding(.vertical, 8)\n                .card()\n            }\n'''
if old_route not in c: raise SystemExit('audio route card not found')
c = c.replace(old_route, new_route, 1)
c = c.replace('try session.setCategory(.playback, mode: .default, options: [])', 'try session.setCategory(.playback, mode: .default, options: [.mixWithOthers])', 1)

# Add route picker once.
route_picker = r'''

private struct TextAudioRoutePicker: UIViewRepresentable {
    func makeUIView(context: Context) -> AVRoutePickerView {
        let view = AVRoutePickerView()
        view.prioritizesVideoDevices = false
        view.activeTintColor = .systemBlue
        view.tintColor = .systemBlue
        return view
    }
    func updateUIView(_ uiView: AVRoutePickerView, context: Context) {}
}
'''
c += route_picker
content.write_text(c)

# Text owns Google callback URL scheme in addition to wearmemory-text.
subprocess.run(['/usr/libexec/PlistBuddy','-c','Add :CFBundleURLTypes:1 dict',str(info)], check=True)
subprocess.run(['/usr/libexec/PlistBuddy','-c','Add :CFBundleURLTypes:1:CFBundleURLName string Google OAuth',str(info)], check=True)
subprocess.run(['/usr/libexec/PlistBuddy','-c','Add :CFBundleURLTypes:1:CFBundleURLSchemes array',str(info)], check=True)
subprocess.run(['/usr/libexec/PlistBuddy','-c','Add :CFBundleURLTypes:1:CFBundleURLSchemes:0 string com.googleusercontent.apps.923188036776-mos9ub27f4k3bhnodr8r4n46flsisptj',str(info)], check=True)
subprocess.run(['/usr/libexec/PlistBuddy','-c','Set :CFBundleShortVersionString 1.1.3',str(info)], check=True)
subprocess.run(['/usr/libexec/PlistBuddy','-c','Set :CFBundleVersion 13',str(info)], check=True)
