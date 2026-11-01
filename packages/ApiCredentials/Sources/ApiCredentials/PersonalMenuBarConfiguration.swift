import Foundation
import CoreFoundation

struct PersonalMenuBarConfiguration: Decodable {
    static let bundleIdentifier = "fr.oby.telegram-menubar"
    static let keychainScope = "personal-menubar-v1"

    let schema: Int
    let api_id: Int32
    let api_hash: String

    enum ConfigurationError: Error, LocalizedError {
        case invalidIdentity
        case missingConfiguration
        case invalidCredentials
        case missingProfile
        case invalidProfile

        var errorDescription: String? {
            switch self {
            case .invalidIdentity:
                return "Telegram Menu Bar: the personal build identity is missing or invalid."
            case .missingConfiguration:
                return "Telegram Menu Bar: the private build credentials are missing."
            case .invalidCredentials:
                return "Telegram Menu Bar: valid personal API credentials are required."
            case .missingProfile:
                return "Telegram Menu Bar: import the closed Telegram profile with the installer before opening the app."
            case .invalidProfile:
                return "Telegram Menu Bar: the imported profile is incomplete or uses symbolic links; no data was initialized."
            }
        }
    }

    static func decode(_ data: Data, bundleIdentifier: String?, personalMarker: Any?) throws -> Self {
        guard bundleIdentifier == Self.bundleIdentifier,
              let marker = personalMarker as? NSNumber,
              CFGetTypeID(marker) == CFBooleanGetTypeID(),
              marker.boolValue else {
            throw ConfigurationError.invalidIdentity
        }
        guard !data.isEmpty, data.count <= 4096,
              let value = try? JSONDecoder().decode(Self.self, from: data),
              value.schema == 1,
              value.api_id > 0, value.api_id != 9,
              value.api_hash.count == 32,
              value.api_hash.unicodeScalars.allSatisfy({
                  (48...57).contains($0.value) || (65...70).contains($0.value) || (97...102).contains($0.value)
              }) else {
            throw ConfigurationError.invalidCredentials
        }
        return value
    }

    static func load(bundle: Bundle) throws -> Self {
        guard let url = bundle.url(forResource: "menubar-config", withExtension: "json"),
              let data = try? Data(contentsOf: url, options: .mappedIfSafe) else {
            throw ConfigurationError.missingConfiguration
        }
        return try decode(
            data,
            bundleIdentifier: bundle.bundleIdentifier,
            personalMarker: bundle.object(forInfoDictionaryKey: "PersonalMenuBar")
        )
    }

    static func profileURL(home: URL, fileManager: FileManager = .default) throws -> URL {
        let profile = home.resolvingSymlinksInPath()
            .appendingPathComponent("Library/Application Support/Telegram Menu Bar/profile", isDirectory: true)
            .standardizedFileURL
        guard fileManager.fileExists(atPath: profile.path) else {
            throw ConfigurationError.missingProfile
        }
        guard profile.resolvingSymlinksInPath().standardizedFileURL.path == profile.path else {
            throw ConfigurationError.invalidProfile
        }
        do {
            for directory in [profile, profile.appendingPathComponent("accounts-metadata", isDirectory: true)] {
                let attributes = try fileManager.attributesOfItem(atPath: directory.path)
                guard attributes[.type] as? FileAttributeType == .typeDirectory else {
                    throw ConfigurationError.invalidProfile
                }
            }
            let key = profile.appendingPathComponent(".tempkeyEncrypted")
            let attributes = try fileManager.attributesOfItem(atPath: key.path)
            guard attributes[.type] as? FileAttributeType == .typeRegular,
                  (attributes[.size] as? NSNumber)?.intValue == 64 else {
                throw ConfigurationError.invalidProfile
            }
        } catch {
            throw ConfigurationError.invalidProfile
        }
        return profile
    }
}
