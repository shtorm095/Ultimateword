Editor.swift
import SwiftUI

struct EditorView: View {
    @State private var text = ""

    var body: some View {
        NavigationView {
            VStack {
                
                // Toolbar
                HStack {
                    Button("B") {
                        text = "**" + text + "**"
                    }
                    
                    Button("I") {
                        text = "_" + text + "_"
                    }
                    
                    Button("H1") {
                        text = "# " + text
                    }
                }
                .padding()
                
                // Editor
                TextEditor(text: $text)
                    .padding()
            }
            .navigationTitle("UltimateWord")
        }
    }
}
