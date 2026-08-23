#!/bin/bash
set -euo pipefail

WORK=/tmp/wm-text-installer
rm -rf "$WORK"
mkdir -p "$WORK/TextInstaller"

cat > "$WORK/project.yml" <<'YAML'
name: TextInstaller
options:
  bundleIdPrefix: local.pavel
  deploymentTarget:
    iOS: "15.0"
targets:
  TextInstaller:
    type: application
    platform: iOS
    sources:
      - TextInstaller
    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: local.pavel.WearMemoryTextInstaller
        PRODUCT_NAME: TextInstaller
        SWIFT_VERSION: 5.0
        TARGETED_DEVICE_FAMILY: "1,2"
        CODE_SIGN_STYLE: Manual
        DEVELOPMENT_TEAM: ""
    info:
      path: TextInstaller/Info.plist
      properties:
        CFBundleDisplayName: Text Installer
        CFBundleName: Text Installer
        CFBundleShortVersionString: "1.0"
        CFBundleVersion: "1"
        LSRequiresIPhoneOS: true
        MinimumOSVersion: "15.0"
        UISupportedInterfaceOrientations:
          - UIInterfaceOrientationPortrait
        UIRequiresFullScreen: false
YAML

cat > "$WORK/TextInstaller/AppDelegate.swift" <<'SWIFT'
import UIKit

@main
final class AppDelegate: UIResponder, UIApplicationDelegate {
    var window: UIWindow?

    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?) -> Bool {
        let window = UIWindow(frame: UIScreen.main.bounds)
        window.rootViewController = UINavigationController(rootViewController: ViewController())
        window.makeKeyAndVisible()
        self.window = window
        return true
    }
}
SWIFT

cat > "$WORK/TextInstaller/ViewController.swift" <<'SWIFT'
import UIKit
import UniformTypeIdentifiers
import CryptoKit

final class ViewController: UIViewController, UIDocumentPickerDelegate, UIDocumentInteractionControllerDelegate {
    private let expectedNames = [
        "Text_1.2.9.ipa.part00",
        "Text_1.2.9.ipa.part01",
        "Text_1.2.9.ipa.part02",
        "Text_1.2.9.ipa.part03"
    ]
    private let expectedSHA256 = "2455ac02f3d1b309c9478a869f2939c1ce19b05d67c023cef3514f13fcf23ce6"
    private let expectedSize: Int64 = 317_967_865

    private let statusLabel = UILabel()
    private let selectButton = UIButton(type: .system)
    private let installButton = UIButton(type: .system)
    private var assembledURL: URL?
    private var documentController: UIDocumentInteractionController?

    override func viewDidLoad() {
        super.viewDidLoad()
        title = "Text Installer"
        view.backgroundColor = .systemBackground

        let titleLabel = UILabel()
        titleLabel.text = "WearMemory Text 1.2.9"
        titleLabel.font = .boldSystemFont(ofSize: 24)
        titleLabel.textAlignment = .center

        let infoLabel = UILabel()
        infoLabel.text = "Выбери одновременно 4 части IPA из Google Drive. Приложение соединит их, проверит SHA-256 и подготовит файл для TrollStore."
        infoLabel.numberOfLines = 0
        infoLabel.textAlignment = .center
        infoLabel.font = .systemFont(ofSize: 16)

        statusLabel.text = "Ожидание файлов"
        statusLabel.numberOfLines = 0
        statusLabel.textAlignment = .center
        statusLabel.font = .monospacedSystemFont(ofSize: 14, weight: .regular)

        selectButton.setTitle("Выбрать 4 части из Google Drive", for: .normal)
        selectButton.titleLabel?.font = .boldSystemFont(ofSize: 17)
        selectButton.addTarget(self, action: #selector(selectParts), for: .touchUpInside)

        installButton.setTitle("Открыть IPA в TrollStore", for: .normal)
        installButton.titleLabel?.font = .boldSystemFont(ofSize: 17)
        installButton.isEnabled = false
        installButton.addTarget(self, action: #selector(openInTrollStore), for: .touchUpInside)

        let stack = UIStackView(arrangedSubviews: [titleLabel, infoLabel, statusLabel, selectButton, installButton])
        stack.axis = .vertical
        stack.spacing = 22
        stack.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(stack)

        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.leadingAnchor, constant: 24),
            stack.trailingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.trailingAnchor, constant: -24),
            stack.centerYAnchor.constraint(equalTo: view.safeAreaLayoutGuide.centerYAnchor)
        ])
    }

    @objc private func selectParts() {
        assembledURL = nil
        installButton.isEnabled = false
        statusLabel.text = "Выбери part00, part01, part02 и part03"
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: [UTType.data], asCopy: true)
        picker.delegate = self
        picker.allowsMultipleSelection = true
        present(picker, animated: true)
    }

    func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
        let byName = Dictionary(uniqueKeysWithValues: urls.map { ($0.lastPathComponent, $0) })
        guard urls.count == 4, Set(byName.keys) == Set(expectedNames) else {
            statusLabel.text = "Ошибка: нужны ровно 4 файла:\n" + expectedNames.joined(separator: "\n")
            return
        }

        selectButton.isEnabled = false
        statusLabel.text = "Соединение частей…"

        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self else { return }
            do {
                let output = try self.assemble(parts: self.expectedNames.compactMap { byName[$0] })
                DispatchQueue.main.async {
                    self.assembledURL = output
                    self.installButton.isEnabled = true
                    self.selectButton.isEnabled = true
                    self.statusLabel.text = "Готово. SHA-256 совпадает.\nРазмер: 317 967 865 байт."
                }
            } catch {
                DispatchQueue.main.async {
                    self.selectButton.isEnabled = true
                    self.installButton.isEnabled = false
                    self.statusLabel.text = "Ошибка: \(error.localizedDescription)"
                }
            }
        }
    }

    private func assemble(parts: [URL]) throws -> URL {
        let fm = FileManager.default
        let docs = try fm.url(for: .documentDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
        let output = docs.appendingPathComponent("Text_1.2.9.ipa")
        try? fm.removeItem(at: output)
        fm.createFile(atPath: output.path, contents: nil)

        let out = try FileHandle(forWritingTo: output)
        defer { try? out.close() }

        var hasher = SHA256()
        var total: Int64 = 0

        for part in parts {
            let input = try FileHandle(forReadingFrom: part)
            defer { try? input.close() }
            while true {
                autoreleasepool {
                    // Keep peak memory low on old iPod hardware.
                }
                let data = try input.read(upToCount: 1_048_576) ?? Data()
                if data.isEmpty { break }
                try out.write(contentsOf: data)
                hasher.update(data: data)
                total += Int64(data.count)
            }
        }

        try out.synchronize()
        guard total == expectedSize else {
            try? fm.removeItem(at: output)
            throw InstallerError.badSize(total)
        }

        let digest = hasher.finalize().map { String(format: "%02x", $0) }.joined()
        guard digest == expectedSHA256 else {
            try? fm.removeItem(at: output)
            throw InstallerError.badHash(digest)
        }
        return output
    }

    @objc private func openInTrollStore() {
        guard let url = assembledURL else { return }
        let controller = UIDocumentInteractionController(url: url)
        controller.delegate = self
        documentController = controller

        if !controller.presentOpenInMenu(from: installButton.bounds, in: installButton, animated: true) {
            let exportPicker = UIDocumentPickerViewController(forExporting: [url], asCopy: true)
            present(exportPicker, animated: true)
            statusLabel.text = "TrollStore не появился в меню. IPA открыт для сохранения в «Файлы»; затем открой Text_1.2.9.ipa через TrollStore."
        }
    }

    enum InstallerError: LocalizedError {
        case badSize(Int64)
        case badHash(String)

        var errorDescription: String? {
            switch self {
            case .badSize(let value):
                return "неверный размер собранного IPA: \(value) байт"
            case .badHash(let value):
                return "SHA-256 не совпал: \(value)"
            }
        }
    }
}
SWIFT

if ! command -v xcodegen >/dev/null 2>&1; then
  brew install xcodegen
fi
cd "$WORK"
xcodegen generate

xcodebuild \
  -project TextInstaller.xcodeproj \
  -scheme TextInstaller \
  -configuration Release \
  -sdk iphoneos \
  -derivedDataPath "$WORK/DerivedData" \
  CODE_SIGNING_ALLOWED=NO \
  CODE_SIGNING_REQUIRED=NO \
  CODE_SIGN_IDENTITY="" \
  ONLY_ACTIVE_ARCH=NO \
  ARCHS=arm64 \
  build

APP="$WORK/DerivedData/Build/Products/Release-iphoneos/TextInstaller.app"
test -d "$APP"
file "$APP/TextInstaller" | grep -q 'arm64'
/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$APP/Info.plist" | grep -Fx 'local.pavel.WearMemoryTextInstaller'
/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Info.plist" | grep -Fx '1.0'
/usr/libexec/PlistBuddy -c 'Print :MinimumOSVersion' "$APP/Info.plist" | grep -Fx '15.0'
strings "$APP/TextInstaller" > "$WORK/strings.txt"
grep -Fq '2455ac02f3d1b309c9478a869f2939c1ce19b05d67c023cef3514f13fcf23ce6' "$WORK/strings.txt"
grep -Fq 'Text_1.2.9.ipa.part00' "$WORK/strings.txt"
grep -Fq 'Text_1.2.9.ipa.part03' "$WORK/strings.txt"

mkdir -p "$WORK/Payload"
cp -R "$APP" "$WORK/Payload/"
OUT=/tmp/Text_Installer_1.0_TrollStore_iOS15.tipa
rm -f "$OUT"
(cd "$WORK" && zip -qry "$OUT" Payload)
unzip -t "$OUT"
shasum -a 256 "$OUT" | tee "$OUT.sha256"
ls -lh "$OUT"
