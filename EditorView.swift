import SwiftUI

struct EditorView: View {
    @StateObject private var viewModel = EditorViewModel()
    @State private var isExporterPresented = false
    @State private var exportedDocument = DOCXFileDocument(data: Data())

    var body: some View {
        NavigationStack {
            VStack(spacing: 12) {
                FormattingToolbar(
                    onBold: viewModel.applyBold,
                    onItalic: viewModel.applyItalic,
                    onHeading1: { viewModel.applyHeading(.h1) },
                    onHeading2: { viewModel.applyHeading(.h2) }
                )

                RichTextEditor(
                    attributedText: $viewModel.attributedText,
                    selectedRange: $viewModel.selectedRange
                )
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .padding(8)
                .background(.background)
                .overlay(
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(.quaternary, lineWidth: 1)
                )

                HStack {
                    Text(viewModel.selectionSummary)
                        .font(.footnote)
                        .foregroundStyle(.secondary)

                    Spacer()

                    Button {
                        do {
                            let documentData = try viewModel.exportDOCX()
                            exportedDocument = DOCXFileDocument(data: documentData)
                            isExporterPresented = true
                        } catch {
                            viewModel.errorMessage = error.localizedDescription
                        }
                    } label: {
                        Label("Export DOCX", systemImage: "square.and.arrow.up")
                    }
                    .buttonStyle(.borderedProminent)
                }
            }
            .padding()
            .navigationTitle("UltimateWord")
            .fileExporter(
                isPresented: $isExporterPresented,
                document: exportedDocument,
                contentType: .docx,
                defaultFilename: "Document"
            ) { _ in }
            .alert(
                "Export Error",
                isPresented: Binding(
                    get: { viewModel.errorMessage != nil },
                    set: { isPresented in
                        if !isPresented {
                            viewModel.errorMessage = nil
                        }
                    }
                ),
                actions: {
                    Button("OK") {
                        viewModel.errorMessage = nil
                    }
                },
                message: {
                    Text(viewModel.errorMessage ?? "Unknown error")
                }
            )
        }
    }
}

private struct FormattingToolbar: View {
    let onBold: () -> Void
    let onItalic: () -> Void
    let onHeading1: () -> Void
    let onHeading2: () -> Void

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                Button(action: onBold) {
                    Label("Bold", systemImage: "bold")
                }
                .buttonStyle(.bordered)

                Button(action: onItalic) {
                    Label("Italic", systemImage: "italic")
                }
                .buttonStyle(.bordered)

                Button("H1", action: onHeading1)
                    .buttonStyle(.bordered)

                Button("H2", action: onHeading2)
                    .buttonStyle(.bordered)
            }
        }
    }
}
