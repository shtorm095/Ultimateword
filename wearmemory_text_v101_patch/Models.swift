import Foundation

enum TextLanguage: String, CaseIterable, Identifiable, Codable {
    case german = "de-DE"
    case russian = "ru-RU"
    case english = "en-US"

    var id: String { rawValue }
    var title: String {
        switch self {
        case .german: return "Deutsch"
        case .russian: return "Русский"
        case .english: return "English"
        }
    }
}

struct AudioBridgeMetadata: Codable {
    let bridgeVersion: Int?
    let sourceFileName: String
    let startedAt: Date
    let endedAt: Date
    let exportedAt: Date?
}

struct TranscriptResult: Codable, Identifiable {
    var id: String { sourceFileName }
    let sourceFileName: String
    let startedAt: Date
    let endedAt: Date
    let processedAt: Date
    let language: String
    let text: String
    var warnings: [String]? = nil
}

struct TextQueueItem: Codable, Identifiable {
    enum State: String, Codable {
        case queued
        case processing
        case retry
    }

    let id: String
    let sourceFileName: String
    var state: State
    var attempts: Int
    var lastError: String?
    var nextRetryAt: Date?
    let discoveredAt: Date
    var nextPieceIndex: Int? = nil
    var completedPieceTexts: [String]? = nil
    var currentPartialText: String? = nil
    var warnings: [String]? = nil
    var lastUnderlyingError: String? = nil
}

struct AudioModuleStatus: Codable {
    let bridgeVersion: Int?
    let module: String?
    let appVersion: String?
    let build: String?
    let isRecording: Bool?
    let audioStatus: String?
    let driveStatus: String?
    let drivePendingCount: Int?
    let driveLastError: String?
    let lastCompletedAudioFile: String?
    let lastCompletedAt: Date?
    let updatedAt: Date?
}
