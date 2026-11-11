import Foundation

/// The foot of the shell settings: which NX2Apple made this iPhone app, and when. The Windows launcher writes both into the
/// app's Info.plist as it makes the IPA (`DMLauncherVersion`, `DMExportedAt`: frontend-qt nspb_qt/win/shell_export.py), and
/// its Send to iPhone window shows the same version for the IPA it offers, so the player can tell the app they installed is
/// the new one. An app made before the launcher wrote them has neither.
struct ShellAppVersion: Equatable {
    var version: String?
    var made: Date?

    init(info: [String: Any]?) {
        version = (info?["DMLauncherVersion"] as? String).flatMap { $0.isEmpty ? nil : $0 }
        made = (info?["DMExportedAt"] as? String).flatMap { try? Date($0, strategy: .iso8601) }
    }

    static var current: ShellAppVersion { ShellAppVersion(info: Bundle.main.infoDictionary) }
}
