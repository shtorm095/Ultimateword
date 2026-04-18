import Foundation
import SwiftUI
import UniformTypeIdentifiers

#if canImport(WordGenerator)
import WordGenerator
#endif

#if canImport(ZIPFoundation)
import ZIPFoundation
#endif

protocol DOCXExporting {
    func export(_ attributedText: NSAttributedString) throws -> Data
}

enum DOCXExportError: Error {
    case zipUnavailable
    case archiveCreationFailed
    case archiveWriteFailed
}

struct DOCXExporter: DOCXExporting {
    private let generator: DocumentXMLGenerating

    init(generator: DocumentXMLGenerating = WordGeneratorAdapter()) {
        self.generator = generator
    }

    func export(_ attributedText: NSAttributedString) throws -> Data {
        let documentXML = generator.makeDocumentXML(from: attributedText)

        #if canImport(ZIPFoundation)
        let tempURL = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
            .appendingPathExtension("docx")

        guard let archive = Archive(url: tempURL, accessMode: .create) else {
            throw DOCXExportError.archiveCreationFailed
        }

        try archive.addDataEntry(path: "[Content_Types].xml", data: contentTypesXML.data(using: .utf8)!)
        try archive.addDataEntry(path: "_rels/.rels", data: rootRelsXML.data(using: .utf8)!)
        try archive.addDataEntry(path: "word/document.xml", data: documentXML.data(using: .utf8)!)

        guard let data = try? Data(contentsOf: tempURL) else {
            throw DOCXExportError.archiveWriteFailed
        }

        try? FileManager.default.removeItem(at: tempURL)
        return data
        #else
        _ = documentXML
        throw DOCXExportError.zipUnavailable
        #endif
    }

    private var contentTypesXML: String {
        """
        <?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
        <Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">
            <Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>
            <Default Extension=\"xml\" ContentType=\"application/xml\"/>
            <Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>
        </Types>
        """
    }

    private var rootRelsXML: String {
        """
        <?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
        <Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">
            <Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/>
        </Relationships>
        """
    }
}

protocol DocumentXMLGenerating {
    func makeDocumentXML(from attributedText: NSAttributedString) -> String
}

struct WordGeneratorAdapter: DocumentXMLGenerating {
    func makeDocumentXML(from attributedText: NSAttributedString) -> String {
        #if canImport(WordGenerator)
        // Integrate the external WordGenerator package when it is linked in the app target.
        // Replace this fallback with the package-specific API call if you need richer conversion.
        #endif

        let escaped = attributedText.string
            .replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")

        return """
        <?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
        <w:document xmlns:wpc=\"http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas\"
                    xmlns:mc=\"http://schemas.openxmlformats.org/markup-compatibility/2006\"
                    xmlns:o=\"urn:schemas-microsoft-com:office:office\"
                    xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\"
                    xmlns:m=\"http://schemas.openxmlformats.org/officeDocument/2006/math\"
                    xmlns:v=\"urn:schemas-microsoft-com:vml\"
                    xmlns:wp14=\"http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing\"
                    xmlns:wp=\"http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing\"
                    xmlns:w10=\"urn:schemas-microsoft-com:office:word\"
                    xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\"
                    mc:Ignorable=\"w14 wp14\">
          <w:body>
            <w:p>
              <w:r>
                <w:t>\(escaped)</w:t>
              </w:r>
            </w:p>
            <w:sectPr>
              <w:pgSz w:w=\"12240\" w:h=\"15840\"/>
              <w:pgMar w:top=\"1440\" w:right=\"1440\" w:bottom=\"1440\" w:left=\"1440\" w:header=\"708\" w:footer=\"708\" w:gutter=\"0\"/>
            </w:sectPr>
          </w:body>
        </w:document>
        """
    }
}

struct DOCXFileDocument: FileDocument {
    static var readableContentTypes: [UTType] { [.docx] }

    let data: Data

    init(data: Data) {
        self.data = data
    }

    init(configuration: ReadConfiguration) throws {
        data = configuration.file.regularFileContents ?? Data()
    }

    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper {
        FileWrapper(regularFileWithContents: data)
    }
}

private extension UTType {
    static let docx = UTType(filenameExtension: "docx") ?? .data
}

#if canImport(ZIPFoundation)
private extension Archive {
    func addDataEntry(path: String, data: Data) throws {
        try addEntry(
            with: path,
            type: .file,
            uncompressedSize: UInt32(data.count),
            provider: { position, size in
                let lowerBound = Int(position)
                let upperBound = lowerBound + size
                return data[lowerBound..<upperBound]
            }
        )
    }
}
#endif
