import Foundation

/// Play on a game built from a version its engine profile was not brought up on (the manifest's `version_supported` is false,
/// written by the Windows launcher at export). Such a game often stops at start (Super Mario Odyssey 1.0.0 crashed in its SDK's
/// startup where 1.4.1 plays), so the shell says why and asks before handing the process over, instead of closing without a word.
public struct VersionWarning: Equatable, Sendable, Identifiable {
    /// The game's title ID.
    public let id: String
    public let message: String

    /// Nil when the manifest says nothing about the version or says it is supported.
    static func make(id: String, name: String, manifest: GameManifest) -> VersionWarning? {
        guard manifest.versionSupported == false else { return nil }
        let built = manifest.displayVersion.isEmpty ? manifest.packageVersion : manifest.displayVersion
        let supported = (manifest.supportedVersions ?? []).joined(separator: ", ")
        let wanted = supported.isEmpty ? "?" : supported
        return VersionWarning(id: id, message: hostText(
            "\(name) was built from version \(built), but it only runs in version \(wanted). It will most likely crash at start. Build it again on the PC with update \(wanted)."))
    }
}
