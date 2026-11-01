import Cocoa

public final class ApiEnvironment {
    #if PERSONAL_MENUBAR
    private static let personalConfiguration: PersonalMenuBarConfiguration = {
        do {
            return try PersonalMenuBarConfiguration.load(bundle: .main)
        } catch {
            fatalError(error.localizedDescription)
        }
    }()
    #endif

    private static func validateBuildIdentity() {
        #if PERSONAL_MENUBAR
        _ = personalConfiguration
        #else
        guard Bundle.main.bundleIdentifier != PersonalMenuBarConfiguration.bundleIdentifier,
              Bundle.main.object(forInfoDictionaryKey: "PersonalMenuBar") == nil else {
            fatalError("Telegram Menu Bar: PERSONAL_MENUBAR was not enabled for ApiCredentials.")
        }
        #endif
    }

    public static var isPersonalMenuBarBuild: Bool {
        validateBuildIdentity()
        #if PERSONAL_MENUBAR
        return true
        #else
        return false
        #endif
    }

    public static var keychainScope: String? {
        validateBuildIdentity()
        #if PERSONAL_MENUBAR
        return PersonalMenuBarConfiguration.keychainScope
        #else
        return prefix == "debug" ? "debug" : nil
        #endif
    }

    public static var apiId:Int32 {
        validateBuildIdentity()
        #if PERSONAL_MENUBAR
        return personalConfiguration.api_id
        #else
        return 9
        #endif
    }
    public static var apiHash:String {
        validateBuildIdentity()
        #if PERSONAL_MENUBAR
        return personalConfiguration.api_hash
        #else
        return "3975f648bb682ee889f35483bc618d1c"
        #endif
    }
    
    public static var bundleId: String {
        validateBuildIdentity()
        #if PERSONAL_MENUBAR
        return PersonalMenuBarConfiguration.bundleIdentifier
        #else
        return "ru.keepcoder.Telegram"
        #endif
    }
    public static var teamId: String {
        validateBuildIdentity()
        #if PERSONAL_MENUBAR
        return ""
        #else
        return "6N38VWS5BX"
        #endif
    }
    
    
    
    public static var containerURL: URL? {
        validateBuildIdentity()
        #if PERSONAL_MENUBAR
        do {
            return try PersonalMenuBarConfiguration.profileURL(home: FileManager.default.homeDirectoryForCurrentUser)
        } catch {
            fatalError(error.localizedDescription)
        }
        #else
        let appGroupName = ApiEnvironment.group
        let containerUrl = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroupName)?.appendingPathComponent(prefix)
        if let containerUrl = containerUrl {
            try? FileManager.default.createDirectory(at: containerUrl, withIntermediateDirectories: true, attributes: nil)
            return containerUrl
        }
        return nil
        #endif
    }
    
    public static func migrate() {
        validateBuildIdentity()
        #if PERSONAL_MENUBAR
        _ = containerURL
        #else
        if let containerURL = containerURL, let legacy = legacyContainerURL, let sequence = FileManager.default.enumerator(atPath: legacy.path) {
            let contents = try? FileManager.default.contentsOfDirectory(at: containerURL, includingPropertiesForKeys: nil, options: [])
            if let contents = contents, !contents.isEmpty {
                return
            }
            for value in sequence {
                if let value = value as? String {
                    if !prefixList.contains(value) {
                        try? FileManager.default.moveItem(at: legacy.appendingPathComponent(value), to: containerURL.appendingPathComponent(value))
                    }
                }
            }
        }
        #endif
    }
    
    public static var legacyContainerURL: URL? {
        validateBuildIdentity()
        #if PERSONAL_MENUBAR
        return nil
        #else
        let appGroupName = ApiEnvironment.group
        let containerUrl = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroupName)
        return containerUrl
        #endif
    }
    
    public static var group: String {
        validateBuildIdentity()
        #if PERSONAL_MENUBAR
        return bundleId
        #else
        return teamId + "." + bundleId
        #endif
    }
    
    public static var appData: Data {
        let apiData = evaluateApiData() ?? ""
        let dict:[String: String] = ["bundleId": bundleId, "data": apiData]
        return try! JSONSerialization.data(withJSONObject: dict, options: [])
    }
    public static var language: String {
        return "macos"
    }
    
    public static var prefixList:[String] {
        return ["debug", "stable", "appstore", "beta"]
    }
    
    public static var prefix: String {
        validateBuildIdentity()
        #if PERSONAL_MENUBAR
        return "menubar"
        #else
        var prefix: String = ""
        switch Configuration.value(for: .source) {
        case "DEBUG":
            prefix = "debug"
        case "STABLE":
            prefix = "stable"
        case "APP_STORE":
            prefix = "appstore"
        default:
            prefix = "beta"
        }
        return prefix
        #endif
    }
    
    public static var version: String {
        var suffix: String = ""
        
        suffix = Configuration.value(for: .source) ?? "DEBUG"
        let shortVersion = Bundle.main.infoDictionary?["CFBundleShortVersionString"] ?? ""
        return "\(shortVersion) \(suffix)"
    }
    
}



