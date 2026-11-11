import Foundation
import Testing
@testable import ShellHost

/// A game the Windows launcher marked as built from a version its profile was not brought up on asks before Play, instead of
/// crashing at start without a word (Super Mario Odyssey 1.0.0 did, where 1.4.1 plays).
@MainActor @Suite struct VersionWarningTests {
    private func mark(_ box: Sandbox, supported: Bool, versions: [String] = ["1.4.1"]) throws {
        let url = box.games.appendingPathComponent(Fixtures.orbit, isDirectory: true).appendingPathComponent("game.manifest.json")
        var json = try #require(try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        json["version_supported"] = supported
        json["supported_versions"] = versions
        try JSONSerialization.data(withJSONObject: json, options: [.prettyPrinted, .sortedKeys]).write(to: url)
    }

    @Test func anUnsupportedVersionAsksFirstAndStartsOnlyWhenThePlayerSaysSo() async throws {
        let box = try Sandbox()
        try box.giveAppData()
        try mark(box, supported: false)
        let launcher = RecordingLauncher()
        let model = ShellHostModel(config: box.config(), launcher: launcher)

        await model.playNow(Fixtures.orbit)
        #expect(launcher.launched.isEmpty, "Play waits for the answer")
        let warning = try #require(model.versionWarning)
        #expect(warning.id == Fixtures.orbit)
        #expect(warning.message.contains("1.0.0") && warning.message.contains("1.4.1"), "built and supported versions: \(warning.message)")

        model.playDespiteVersion(warning.id)
        #expect(model.versionWarning == nil)
        for _ in 0..<200 where launcher.launched.isEmpty { try await Task.sleep(for: .milliseconds(10)) }
        #expect(launcher.launched.count == 1, "Play anyway starts the game")
        #expect(model.versionWarning == nil, "the confirmed Play does not ask again")
    }

    @Test(arguments: [true, nil]) func aSupportedOrUnmarkedGameStartsAtOnce(supported: Bool?) async throws {
        let box = try Sandbox()
        try box.giveAppData()
        if let supported { try mark(box, supported: supported) }
        let launcher = RecordingLauncher()
        let model = ShellHostModel(config: box.config(), launcher: launcher)
        await model.playNow(Fixtures.orbit)
        #expect(launcher.launched.count == 1)
        #expect(model.versionWarning == nil)
    }

    @Test func theManifestReadsTheLaunchersKeysAndOlderManifestsLackThem() throws {
        let url = Fixtures.gamesURL.appendingPathComponent(Fixtures.orbit, isDirectory: true).appendingPathComponent("game.manifest.json")
        let plain = try GameManifest.parse(Data(contentsOf: url))
        #expect(plain.versionSupported == nil && plain.supportedVersions == nil)
        #expect(VersionWarning.make(id: Fixtures.orbit, name: "Orbit", manifest: plain) == nil)

        var json = try #require(try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        json["version_supported"] = false
        json["supported_versions"] = ["1.4.1", "1.4.2"]
        let marked = try GameManifest.parse(JSONSerialization.data(withJSONObject: json))
        #expect(marked.versionSupported == false && marked.supportedVersions == ["1.4.1", "1.4.2"])
        let warning = try #require(VersionWarning.make(id: Fixtures.orbit, name: "Orbit", manifest: marked))
        #expect(warning.message.contains("Orbit") && warning.message.contains("1.4.1, 1.4.2"))
    }
}
