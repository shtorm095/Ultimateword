from pathlib import Path
import subprocess

root = Path('/tmp/wmtext115-src')
content = root/'WearMemoryText/ContentView.swift'
proc = root/'WearMemoryText/TextProcessor.swift'
info = root/'WearMemoryText/Info.plist'

c = content.read_text()

# Show Tablette result independently between iPad and PC.
old_ui = '''                                    Text(item.ipadStatusText)\n                                        .font(.caption.weight(.semibold))\n                                        .foregroundColor(item.ipadStatus == "ready" ? .green : (item.ipadStatus == "not_ready" ? .orange : .secondary))\n                                    if let pc = item.pcStatusText {\n                                        Text(pc)\n                                            .font(.caption.weight(.semibold))\n                                            .foregroundColor(item.pcStatus == "ready" ? .green : .orange)\n                                    }\n                                    if let error = item.visibleError, !error.isEmpty {\n'''
new_ui = '''                                    Text(item.ipadStatusText)\n                                        .font(.caption.weight(.semibold))\n                                        .foregroundColor(item.ipadStatus == "ready" ? .green : (item.ipadStatus == "not_ready" ? .orange : .secondary))\n                                    if let tablet = item.tabletStatusText {\n                                        Text(tablet)\n                                            .font(.caption.weight(.semibold))\n                                            .foregroundColor(item.tabletStatus == "ready" ? .green : .orange)\n                                    }\n                                    if let pc = item.pcStatusText {\n                                        Text(pc)\n                                            .font(.caption.weight(.semibold))\n                                            .foregroundColor(item.pcStatus == "ready" ? .green : .orange)\n                                    }\n                                    if let error = item.visibleError, !error.isEmpty {\n'''
if old_ui not in c:
    raise SystemExit('status UI insertion point not found')
c = c.replace(old_ui, new_ui, 1)

# Add independent Tablette fields to the in-memory audio model.
old_fields = '''    let ipadStatus: String?\n    let ipadError: String?\n    let pcStatus: String?\n    let pcError: String?\n'''
new_fields = '''    let ipadStatus: String?\n    let ipadError: String?\n    let tabletStatus: String?\n    let tabletError: String?\n    let pcStatus: String?\n    let pcError: String?\n'''
if old_fields not in c:
    raise SystemExit('AudioInboxFile status fields not found')
c = c.replace(old_fields, new_fields, 1)

old_pc_status = '''    var pcStatusText: String? {\n        switch pcStatus {\n        case "ready": return "Готов на ПК"\n        case "not_ready": return "Не готов на ПК"\n        default: return nil\n        }\n    }\n\n    var visibleError: String? {\n        if ipadStatus == "not_ready", let ipadError = ipadError { return "iPad: \\(ipadError)" }\n        if pcStatus == "not_ready", let pcError = pcError { return "ПК: \\(pcError)" }\n        return nil\n    }\n'''
new_pc_status = '''    var tabletStatusText: String? {\n        switch tabletStatus {\n        case "ready": return "Готов на Tablette"\n        case "not_ready": return "Не готов на Tablette"\n        default: return nil\n        }\n    }\n\n    var pcStatusText: String? {\n        switch pcStatus {\n        case "ready": return "Готов на ПК"\n        case "not_ready": return "Не готов на ПК"\n        default: return nil\n        }\n    }\n\n    var visibleError: String? {\n        var errors: [String] = []\n        if ipadStatus == "not_ready", let ipadError = ipadError, !ipadError.isEmpty { errors.append("iPad: \\(ipadError)") }\n        if tabletStatus == "not_ready", let tabletError = tabletError, !tabletError.isEmpty { errors.append("Tablette: \\(tabletError)") }\n        if pcStatus == "not_ready", let pcError = pcError, !pcError.isEmpty { errors.append("ПК: \\(pcError)") }\n        return errors.isEmpty ? nil : errors.joined(separator: "\\n")\n    }\n'''
if old_pc_status not in c:
    raise SystemExit('PC status/visibleError block not found')
c = c.replace(old_pc_status, new_pc_status, 1)

old_map = '''                    ipadStatus: status.ipadStatus, ipadError: status.ipadError,\n                    pcStatus: status.pcStatus, pcError: status.pcError\n'''
new_map = '''                    ipadStatus: status.ipadStatus, ipadError: status.ipadError,\n                    tabletStatus: status.tabletStatus, tabletError: status.tabletError,\n                    pcStatus: status.pcStatus, pcError: status.pcError\n'''
if old_map not in c:
    raise SystemExit('AudioInboxFile mapping block not found')
c = c.replace(old_map, new_map, 1)

old_helper = '''    private static func readStatusMetadata(for audioURL: URL) -> (ipadStatus: String?, ipadError: String?, pcStatus: String?, pcError: String?) {\n        let metaURL = audioURL.deletingPathExtension().appendingPathExtension("meta.json")\n        guard let data = try? Data(contentsOf: metaURL),\n              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {\n            return (nil, nil, nil, nil)\n        }\n\n        var ipadStatus = object["ipadStatus"] as? String\n        if ipadStatus == nil, let legacy = object["speechStatus"] as? String {\n            if legacy == "recognized_complete" { ipadStatus = "ready" }\n            if legacy == "needs_pc" { ipadStatus = "not_ready" }\n        }\n        let ipadError = (object["ipadErrorMessage"] as? String) ?? (object["speechReason"] as? String)\n        // pcStatus is read-only in the iPad app. It is written later by the computer.\n        let pcStatus = object["pcStatus"] as? String\n        let pcError = object["pcErrorMessage"] as? String\n        return (ipadStatus, ipadError, pcStatus, pcError)\n    }\n'''
new_helper = '''    private static func readStatusMetadata(for audioURL: URL) -> (ipadStatus: String?, ipadError: String?, tabletStatus: String?, tabletError: String?, pcStatus: String?, pcError: String?) {\n        let metaURL = audioURL.deletingPathExtension().appendingPathExtension("meta.json")\n        guard let data = try? Data(contentsOf: metaURL),\n              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {\n            return (nil, nil, nil, nil, nil, nil)\n        }\n\n        var ipadStatus = object["ipadStatus"] as? String\n        if ipadStatus == nil, let legacy = object["speechStatus"] as? String {\n            if legacy == "recognized_complete" { ipadStatus = "ready" }\n            if legacy == "needs_pc" { ipadStatus = "not_ready" }\n        }\n        let ipadError = (object["ipadErrorMessage"] as? String) ?? (object["speechReason"] as? String)\n\n        // Tablette and PC statuses are read-only here. They are written later by those devices.\n        let tabletStatus = object["tabletStatus"] as? String\n        let tabletError = object["tabletErrorMessage"] as? String\n        let pcStatus = object["pcStatus"] as? String\n        let pcError = object["pcErrorMessage"] as? String\n        return (ipadStatus, ipadError, tabletStatus, tabletError, pcStatus, pcError)\n    }\n'''
if old_helper not in c:
    raise SystemExit('readStatusMetadata helper not found')
c = c.replace(old_helper, new_helper, 1)

content.write_text(c)

# The iPad processor must preserve, but never create or overwrite, Tablette/PC states.
p = proc.read_text()
p = p.replace(
    '// Explicit iPad state. The iPad application NEVER writes pcStatus/pcError*.',
    '// Explicit iPad state. The iPad application NEVER writes tabletStatus/tabletError* or pcStatus/pcError*.',
    1
)
proc.write_text(p)

subprocess.run(['/usr/libexec/PlistBuddy','-c','Set :CFBundleShortVersionString 1.1.5',str(info)], check=True)
subprocess.run(['/usr/libexec/PlistBuddy','-c','Set :CFBundleVersion 15',str(info)], check=True)

print('patched v1.1.5 with independent iPad / Tablette / PC status fields')
