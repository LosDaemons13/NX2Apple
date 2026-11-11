import Foundation
import Testing
@testable import ShellUI

/// The settings' Version row reads what the Windows launcher wrote into the app as it made the IPA (shell_export.py).
struct ShellAppVersionTests {
    @Test func theLauncherVersionAndTheDateItMadeTheApp() throws {
        let v = ShellAppVersion(info: ["DMLauncherVersion": "1.4.0.18", "DMExportedAt": "2026-11-12T13:32:05Z"])
        #expect(v.version == "1.4.0.18")
        let made = try #require(v.made)
        #expect(made == Date(timeIntervalSince1970: 1_794_490_325))
    }

    @Test func anAppMadeBeforeTheLauncherWroteThemHasNeither() {
        #expect(ShellAppVersion(info: ["CFBundleShortVersionString": "1.0"]) == ShellAppVersion(info: nil))
        let odd = ShellAppVersion(info: ["DMLauncherVersion": "", "DMExportedAt": "yesterday"])
        #expect(odd.version == nil && odd.made == nil)
    }
}
