import Foundation

extension TextProcessor {
    func journalFiles() -> [URL] {
        let fm = FileManager.default
        try? fm.createDirectory(at: journalsDirectory, withIntermediateDirectories: true)
        return ((try? fm.contentsOfDirectory(at: journalsDirectory, includingPropertiesForKeys: [.contentModificationDateKey], options: [.skipsHiddenFiles])) ?? [])
            .filter { $0.pathExtension.lowercased() == "txt" }
            .sorted { $0.lastPathComponent > $1.lastPathComponent }
    }
}
