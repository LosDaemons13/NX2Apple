import SwiftUI

/// The open case in front of the library: Play on a ready game opens its case (`GameCaseView`) instead of starting it at
/// once. The case starts the game when its cartridge clicks into the slot. While it is open, the controller's A inserts
/// the cartridge, B closes the case and X opens the game's settings over it.
extension LibraryView {
    /// The game whose case is open, while it is still in the library.
    var caseDetail: GameDetail? {
        guard let caseGameID else { return nil }
        return games.first { $0.id == caseGameID }
    }

    func openCase(_ id: String) {
        guard caseGameID == nil else { return }
        if selectedID != id { selectedID = id }
        caseCommand = CaseCommand()
        caseGameID = id
    }

    /// Not through `guardedActions`: the start comes a second after the press, never as the system's echo of a button.
    func launchFromCase(_ id: String) {
        actions.onPlay(id)
    }

    func openCaseInfo(_ id: String) {
        if selectedID != id { selectedID = id }
        openSettings()
    }

    func closedCase(_ id: String) {
        guard caseGameID == id else { return }
        caseGameID = nil
        focus.id = "lib.tile.\(id)"
    }

    /// A controller or key press while the case is the top layer. True when the case took it.
    func handleCase(_ action: ShellInput.Action) -> Bool {
        guard caseGameID != nil, topLayer == nil else { return false }
        guard caseDetail != nil else {
            // The game left the library while its case was open.
            caseGameID = nil
            return false
        }
        switch action {
        case .activate: caseCommand.send(.insert)
        case .back: caseCommand.send(.close)
        case .settings: if let caseGameID { openCaseInfo(caseGameID) }
        case .up, .down, .left, .right, .controllers, .shellSettings: break
        }
        return true
    }
}
