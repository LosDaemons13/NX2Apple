import SwiftUI

/// Focus geometry and activation are transient UI state. Hardware belongs to the caller.
struct FocusTarget: Equatable {
    let id: String
    let frame: CGRect
    let activate: () -> Void
    // A new render can change an activation closure without changing its frame or ID.
    private let generation = UUID()
    init(id: String, frame: CGRect, activate: @escaping () -> Void) {
        self.id = id
        self.frame = frame
        self.activate = activate
    }
    static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.id == rhs.id && lhs.frame == rhs.frame && lhs.generation == rhs.generation
    }
}

/// A non-observed UI registry avoids feeding preference updates back into view rendering.
/// It holds only the latest focus geometry and actions, never game or settings state.
@MainActor final class FocusTargetBuffer {
    var values: [FocusTarget] = []
    // Native sheets host their own preferences; retain the library targets while a sheet is open.
    var libraryValues: [FocusTarget] = []
    var toolbarValues: [String: FocusTarget] = [:]

    func active(prefix: String, toolbarIDs: Set<String>) -> [FocusTarget] {
        let content = (libraryValues + values).filter { !toolbarIDs.contains($0.id) }
        let toolbar = toolbarValues.values.filter { toolbarIDs.contains($0.id) }.sorted { $0.id < $1.id }
        return (content + toolbar).filter { $0.id.hasPrefix(prefix) && $0.frame.width > 1 }
    }
}
struct FocusTargets: PreferenceKey {
    static var defaultValue: [FocusTarget] { [] }
    static func reduce(value: inout [FocusTarget], nextValue: () -> [FocusTarget]) { value += nextValue() }
}
struct FocusAppearance: Equatable {
    var id: String?
    var visible = false
}
private struct FocusAppearanceKey: EnvironmentKey {
    static var defaultValue: FocusAppearance { FocusAppearance() }
}
private struct IgnoresPressKey: EnvironmentKey {
    static var defaultValue: () -> Bool { { false } }
}
extension EnvironmentValues {
    /// True while a press is the system's echo of a controller button, not a finger (see `LibraryView.noteTouch`). A
    /// control that moves at once on a press, before its value comes back, asks it first.
    var shellIgnoresPress: () -> Bool {
        get { self[IgnoresPressKey.self] }
        set { self[IgnoresPressKey.self] = newValue }
    }
    var shellFocus: FocusAppearance {
        get { self[FocusAppearanceKey.self] }
        set { self[FocusAppearanceKey.self] = newValue }
    }
}
struct ShellFocusTarget: ViewModifier {
    let id: String
    let enabled: Bool
    /// The ring follows the control's shape: 12 for covers and cards, a large value for capsules and circles.
    let radius: CGFloat
    var showsRing = true
    let action: () -> Void
    /// Radius for capsules and circles: any value above half the control's shorter side draws a full round end.
    static let capsule: CGFloat = 100
    /// The corner radius the ring really draws for a control of `size`: SwiftUI clamps it to half the shorter side.
    nonisolated static func ringCornerRadius(radius: CGFloat, size: CGSize) -> CGFloat {
        min(radius + 5, min(size.width, size.height) / 2 + 5)
    }
    /// Only the focused target draws a ring, and only while focus is visible.
    nonisolated static func drawsRing(showsRing: Bool, visible: Bool, focused: String?, id: String) -> Bool {
        showsRing && visible && focused == id
    }
    @Environment(\.shellFocus) private var focus
    func body(content: Content) -> some View {
        content
            .overlay {
                if Self.drawsRing(showsRing: showsRing, visible: focus.visible, focused: focus.id, id: id) {
                    RoundedRectangle(cornerRadius: radius + 5).strokeBorder(ShellPalette.cream, lineWidth: 3)
                        .padding(-5).allowsHitTesting(false).accessibilityHidden(true)
                        // On and off at once: a ring fading in or out stays where it was while a panel slides, apart
                        // from its control. An animated scroll to the focused row (withAnimation around scrollTo) must not
                        // fade the ring either: the old row's ring lingered and the new one flashed (#1026).
                        .transition(.identity)
                        .transaction { $0.animation = nil; $0.disablesAnimations = true }
                }
            }
            .background {
                if enabled {
                    GeometryReader { geometry in
                        Color.clear.preference(key: FocusTargets.self, value: [
                            FocusTarget(id: id, frame: geometry.frame(in: .global), activate: action)
                        ])
                    }
                }
            }
            .id(id)
    }
}
extension View {
    func shellTarget(_ id: String, enabled: Bool = true, radius: CGFloat = 12, showsRing: Bool = true, action: @escaping () -> Void) -> some View {
        modifier(ShellFocusTarget(id: id, enabled: enabled, radius: radius, showsRing: showsRing, action: action))
    }
}

/// Pure spatial focus selection shared by the UI and its navigation tests.
enum FocusNavigation {
    static func next(from id: String?, action: ShellInput.Action, targets: [FocusTarget]) -> String? {
        guard let origin = targets.first(where: { $0.id == id }) else { return targets.first?.id }
        let candidates = targets.filter { target in
            guard target.id != origin.id else { return false }
            let dx = target.frame.midX - origin.frame.midX
            let dy = target.frame.midY - origin.frame.midY
            switch action {
            case .left: return dx < -8
            case .right: return dx > 8
            case .up: return dy < -8
            case .down: return dy > 8
            default: return false
            }
        }
        func score(_ target: FocusTarget) -> CGFloat {
            let dx = abs(target.frame.midX - origin.frame.midX)
            let dy = abs(target.frame.midY - origin.frame.midY)
            switch action {
            case .left, .right: return dx + dy * 3
            default: return dy + dx * 3
            }
        }
        return candidates.min(by: { score($0) < score($1) })?.id ?? id
    }
}

private struct ShellNativeBarsKey: EnvironmentKey { static let defaultValue = false }
extension EnvironmentValues {
    var shellNativeBars: Bool {
        get { self[ShellNativeBarsKey.self] }
        set { self[ShellNativeBarsKey.self] = newValue }
    }
}

/// Keyboard commands use a non-text responder on iOS, so a context menu cannot summon a text keyboard.
struct ShellKeyboardNavigation: ViewModifier {
    let active: Bool
    let handle: (ShellInput.Action) -> Void
    @FocusState private var focused: Bool
    func body(content: Content) -> some View {
        #if os(iOS)
        content.background { ShellKeyCommands(active: active, handle: handle).frame(width: 0, height: 0) }
        #else
        content.focusable(active).focused($focused).focusEffectDisabled()
            .onAppear { focused = active }
            .onChange(of: active) { _, value in focused = value }
            .onKeyPress(.leftArrow) { press(.left) }
            .onKeyPress(.rightArrow) { press(.right) }
            .onKeyPress(.upArrow) { press(.up) }
            .onKeyPress(.downArrow) { press(.down) }
            .onKeyPress(.return) { press(.activate) }
            .onKeyPress(.escape) { press(.back) }
            .onKeyPress("o") { press(.settings) }
            .onKeyPress("y") { press(.controllers) }
            .onKeyPress(",") { press(.shellSettings) }
        #endif
    }
    private func press(_ action: ShellInput.Action) -> KeyPress.Result {
        guard active else { return .ignored }
        handle(action)
        return .handled
    }
}

#if os(iOS)
extension UIResponder {
    nonisolated(unsafe) private static weak var shellFound: UIResponder?
    @objc private func shellReportFirstResponder(_ sender: Any?) { UIResponder.shellFound = self }

    /// A text field or view of any screen is being typed in. The key command view below took the first responder back at
    /// every update of the views it sits in, and the keyboard opening resizes them: a field on a screen presented over the
    /// shell ("Receive from PC") lost the keyboard as soon as it showed it, so nothing could be typed or pasted there.
    @MainActor static var shellTextIsBeingEdited: Bool {
        shellFound = nil
        UIApplication.shared.sendAction(#selector(shellReportFirstResponder(_:)), to: nil, from: nil, for: nil)   // reaches the first responder
        return shellFound is UITextInput
    }
}

extension UIView {
    /// No other screen is presented over the one this view is in: a sheet, "Receive from PC" over the shell settings, an
    /// alert. A screen on top has its own fields and keys, so the key commands under it leave the keyboard alone.
    @MainActor var shellIsOnTopScreen: Bool {
        guard let window, var top = window.rootViewController else { return false }
        while let next = top.presentedViewController, !next.isBeingDismissed { top = next }
        return isDescendant(of: top.view)
    }
}

/// A screen the host presented over the shell outside SwiftUI ("Receive from PC") closed: the key commands under it take
/// the keyboard back, which no update of their own views would do.
public enum ShellKeyboardFocus {
    static let reclaim = Notification.Name("ShellKeyCommands.reclaim")
    public static func screenClosed() { NotificationCenter.default.post(name: reclaim, object: nil) }
}

private struct ShellKeyCommands: UIViewRepresentable {
    let active: Bool
    let handle: (ShellInput.Action) -> Void
    func makeUIView(context: Context) -> CommandView { CommandView() }
    func updateUIView(_ view: CommandView, context: Context) {
        view.active = active
        view.handle = handle
        if active { view.takeKeyboard() }
        else if view.isFirstResponder { view.resignFirstResponder() }
    }
    final class CommandView: UIView {
        var active = false
        var handle: ((ShellInput.Action) -> Void)?
        private static let actions: [(String, ShellInput.Action)] = [
            (UIKeyCommand.inputLeftArrow, .left), (UIKeyCommand.inputRightArrow, .right),
            (UIKeyCommand.inputUpArrow, .up), (UIKeyCommand.inputDownArrow, .down),
            ("\r", .activate), (UIKeyCommand.inputEscape, .back), ("o", .settings), ("y", .controllers), (",", .shellSettings)
        ]
        override init(frame: CGRect) {
            super.init(frame: frame)
            NotificationCenter.default.addObserver(self, selector: #selector(reclaim(_:)), name: ShellKeyboardFocus.reclaim, object: nil)
        }
        required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }
        override var canBecomeFirstResponder: Bool { active }
        override var keyCommands: [UIKeyCommand]? {
            active ? Self.actions.map { UIKeyCommand(input: $0.0, modifierFlags: [], action: #selector(command(_:))) } : nil
        }
        override func didMoveToWindow() {
            super.didMoveToWindow()
            takeKeyboard()
        }
        /// Takes the first responder for the key commands, unless a text is being typed anywhere or another screen is on
        /// top: "Receive from PC" lost its keyboard as soon as it showed it.
        func takeKeyboard() {
            guard active, window != nil, !isFirstResponder, shellIsOnTopScreen, !UIResponder.shellTextIsBeingEdited else { return }
            becomeFirstResponder()
        }
        @objc private func reclaim(_ note: Notification) { takeKeyboard() }
        @objc private func command(_ command: UIKeyCommand) {
            guard active, let action = Self.actions.first(where: { $0.0 == command.input })?.1 else { return }
            handle?(action)
        }
    }
}
#endif
