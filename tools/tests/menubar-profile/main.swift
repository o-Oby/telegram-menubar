import Foundation

func expectError(_ operation: () throws -> Void) {
    do {
        try operation()
        fatalError("Expected failure")
    } catch {}
}

func credentials(id: Any = 100_001, hash: Any = String(repeating: "a", count: 32), schema: Any = 1) -> Data {
    return try! JSONSerialization.data(withJSONObject: ["schema": schema, "api_id": id, "api_hash": hash])
}

func decode(_ data: Data, identity: String? = "fr.oby.telegram-menubar", marker: Any? = true) throws -> PersonalMenuBarConfiguration {
    return try PersonalMenuBarConfiguration.decode(data, bundleIdentifier: identity, personalMarker: marker)
}

let valid = try decode(credentials())
precondition(valid.api_id == 100_001)
precondition(valid.api_hash == String(repeating: "a", count: 32))
for data in [
    credentials(id: 9), credentials(id: 0), credentials(id: -1), credentials(id: Int64(Int32.max) + 1),
    credentials(id: 1.5), credentials(id: true), credentials(id: "100001"),
    credentials(hash: ""), credentials(hash: String(repeating: "z", count: 32)),
    credentials(hash: String(repeating: "a", count: 31)), credentials(hash: true),
    credentials(schema: 0), credentials(schema: true), Data("{}".utf8), Data("not json".utf8),
    Data(repeating: 32, count: 4097)
] {
    expectError { _ = try decode(data) }
}
for identity in [nil, "ru.keepcoder.Telegram", "fr.oby.other"] {
    expectError { _ = try decode(credentials(), identity: identity) }
}
for marker in [nil, false, "true", NSNumber(value: 1)] as [Any?] {
    expectError { _ = try decode(credentials(), marker: marker) }
}
let uppercase = try decode(credentials(hash: String(repeating: "A", count: 32)))
precondition(uppercase.api_id == 100_001)

let fileManager = FileManager.default
let temporary = fileManager.temporaryDirectory.appendingPathComponent("menubar-profile-tests-" + UUID().uuidString)
try fileManager.createDirectory(at: temporary, withIntermediateDirectories: true)
defer { try? fileManager.removeItem(at: temporary) }
let app = temporary.appendingPathComponent("Fixture.app")
let resources = app.appendingPathComponent("Contents/Resources")
try fileManager.createDirectory(at: resources, withIntermediateDirectories: true)
let info: [String: Any] = ["CFBundleIdentifier": "fr.oby.telegram-menubar", "CFBundlePackageType": "APPL", "PersonalMenuBar": true]
let infoData = try PropertyListSerialization.data(fromPropertyList: info, format: .xml, options: 0)
try infoData.write(to: app.appendingPathComponent("Contents/Info.plist"))
let emptyApp = temporary.appendingPathComponent("Missing.app")
try fileManager.createDirectory(at: emptyApp.appendingPathComponent("Contents/Resources"), withIntermediateDirectories: true)
try infoData.write(to: emptyApp.appendingPathComponent("Contents/Info.plist"))
expectError { _ = try PersonalMenuBarConfiguration.load(bundle: Bundle(url: emptyApp)!) }
try credentials().write(to: resources.appendingPathComponent("menubar-config.json"))
let bundle = Bundle(url: app)!
let bundled = try PersonalMenuBarConfiguration.load(bundle: bundle)
precondition(bundled.api_id == 100_001)
try credentials(id: 9).write(to: resources.appendingPathComponent("menubar-config.json"))
expectError { _ = try PersonalMenuBarConfiguration.load(bundle: bundle) }

let home = temporary.appendingPathComponent("home")
let profile = home.appendingPathComponent("Library/Application Support/Telegram Menu Bar/profile")
expectError { _ = try PersonalMenuBarConfiguration.profileURL(home: home) }
precondition(!fileManager.fileExists(atPath: home.path))
try fileManager.createDirectory(at: profile, withIntermediateDirectories: true)
expectError { _ = try PersonalMenuBarConfiguration.profileURL(home: home) }
let metadata = profile.appendingPathComponent("accounts-metadata")
try fileManager.createDirectory(at: metadata, withIntermediateDirectories: true)
let key = profile.appendingPathComponent(".tempkeyEncrypted")
try Data(repeating: 0, count: 63).write(to: key)
expectError { _ = try PersonalMenuBarConfiguration.profileURL(home: home) }
try Data(repeating: 0, count: 64).write(to: key)
let validatedProfile = try PersonalMenuBarConfiguration.profileURL(home: home)
precondition(validatedProfile == profile.resolvingSymlinksInPath().standardizedFileURL)
let initialKeyAttributes = try fileManager.attributesOfItem(atPath: key.path)
_ = try PersonalMenuBarConfiguration.profileURL(home: home)
let finalKeyAttributes = try fileManager.attributesOfItem(atPath: key.path)
precondition(finalKeyAttributes[.modificationDate] as? Date == initialKeyAttributes[.modificationDate] as? Date)

let externalKey = temporary.appendingPathComponent("external-key")
try fileManager.moveItem(at: key, to: externalKey)
try fileManager.createSymbolicLink(at: key, withDestinationURL: externalKey)
expectError { _ = try PersonalMenuBarConfiguration.profileURL(home: home) }
try fileManager.removeItem(at: key)
try fileManager.moveItem(at: externalKey, to: key)
let externalMetadata = temporary.appendingPathComponent("external-metadata")
try fileManager.moveItem(at: metadata, to: externalMetadata)
try fileManager.createSymbolicLink(at: metadata, withDestinationURL: externalMetadata)
expectError { _ = try PersonalMenuBarConfiguration.profileURL(home: home) }
try fileManager.removeItem(at: metadata)
try fileManager.moveItem(at: externalMetadata, to: metadata)
let original = temporary.appendingPathComponent("original-profile")
try fileManager.moveItem(at: profile, to: original)
try fileManager.createSymbolicLink(at: profile, withDestinationURL: original)
expectError { _ = try PersonalMenuBarConfiguration.profileURL(home: home) }
try fileManager.removeItem(at: profile)
try fileManager.moveItem(at: original, to: profile)
let parent = profile.deletingLastPathComponent()
let externalParent = temporary.appendingPathComponent("external-parent")
try fileManager.moveItem(at: parent, to: externalParent)
try fileManager.createSymbolicLink(at: parent, withDestinationURL: externalParent)
expectError { _ = try PersonalMenuBarConfiguration.profileURL(home: home) }

print("Personal credentials, identity, profile validation and symlink protection passed")
