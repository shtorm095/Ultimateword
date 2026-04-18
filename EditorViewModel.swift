import SwiftUI
import UIKit

@MainActor
final class EditorViewModel: ObservableObject {
    @Published var attributedText: NSAttributedString
    @Published var selectedRange: NSRange
    @Published var errorMessage: String?

    private let exporter: DOCXExporting

    init(exporter: DOCXExporting = DOCXExporter()) {
        self.exporter = exporter

        let attributes: [NSAttributedString.Key: Any] = [
            .font: UIFont.systemFont(ofSize: 16)
        ]
        self.attributedText = NSAttributedString(string: "Start writing…", attributes: attributes)
        self.selectedRange = NSRange(location: 0, length: 0)
    }

    var selectionSummary: String {
        "Selection: \(selectedRange.location)-\(selectedRange.location + selectedRange.length)"
    }

    func applyBold() {
        applyFontTransform { font in
            font.withToggledTrait(.traitBold)
        }
    }

    func applyItalic() {
        applyFontTransform { font in
            font.withToggledTrait(.traitItalic)
        }
    }

    func applyHeading(_ heading: HeadingLevel) {
        guard selectedRange.location <= attributedText.length else { return }

        let mutable = NSMutableAttributedString(attributedString: attributedText)
        let targetRange = selectedRange.length > 0
            ? selectedRange
            : NSRange(location: selectedRange.location, length: 1)

        let clampedRange = clampRange(targetRange, upperBound: mutable.length)
        guard clampedRange.length > 0 else { return }

        mutable.addAttribute(.font, value: heading.font, range: clampedRange)
        attributedText = mutable
    }

    func exportDOCX() throws -> Data {
        try exporter.export(attributedText)
    }

    private func applyFontTransform(_ transform: (UIFont) -> UIFont) {
        let mutable = NSMutableAttributedString(attributedString: attributedText)

        let targetRange = selectedRange.length > 0
            ? selectedRange
            : NSRange(location: selectedRange.location, length: 1)

        let clampedRange = clampRange(targetRange, upperBound: mutable.length)
        guard clampedRange.length > 0 else { return }

        mutable.enumerateAttribute(.font, in: clampedRange) { value, range, _ in
            let existingFont = value as? UIFont ?? UIFont.systemFont(ofSize: 16)
            mutable.addAttribute(.font, value: transform(existingFont), range: range)
        }

        attributedText = mutable
    }

    private func clampRange(_ range: NSRange, upperBound: Int) -> NSRange {
        let start = max(0, min(range.location, upperBound))
        let end = max(start, min(range.location + range.length, upperBound))
        return NSRange(location: start, length: end - start)
    }
}

enum HeadingLevel {
    case h1
    case h2

    var font: UIFont {
        switch self {
        case .h1:
            return .boldSystemFont(ofSize: 32)
        case .h2:
            return .boldSystemFont(ofSize: 24)
        }
    }
}

private extension UIFont {
    func withToggledTrait(_ trait: UIFontDescriptor.SymbolicTraits) -> UIFont {
        var traits = fontDescriptor.symbolicTraits
        if traits.contains(trait) {
            traits.remove(trait)
        } else {
            traits.insert(trait)
        }

        guard let descriptor = fontDescriptor.withSymbolicTraits(traits) else {
            return self
        }

        return UIFont(descriptor: descriptor, size: pointSize)
    }
}
