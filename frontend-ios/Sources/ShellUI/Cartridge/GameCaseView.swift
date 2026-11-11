import SwiftUI

/// What a controller or a key asks of the open case, forwarded by the library: A inserts the cartridge, B closes the case.
struct CaseCommand: Equatable {
    enum Kind: Equatable { case none, insert, close }
    private(set) var sequence = 0
    private(set) var kind: Kind = .none
    mutating func send(_ kind: Kind) {
        sequence += 1
        self.kind = kind
    }
}

/// The game's case, opened in front of the player: the lid on the left holds the manual with the box art, the holder on the
/// right holds the cartridge. Insert cartridge lifts it out, carries it to the slot and pushes it in with a click, then the
/// game starts. The case runs its own animation. The library only forwards the controller's A and B (`command`) and hears
/// back when the game should start (`launch`) or the case has closed (`closed`).
struct GameCaseView: View {
    let detail: GameDetail
    let command: CaseCommand
    /// The cartridge has clicked into the slot: start the game.
    let launch: () -> Void
    /// Open the game's settings over the case.
    let info: () -> Void
    /// The case is closed: the library takes over again.
    let closed: () -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    /// The host disables the library while it prepares a game: that is how the case knows the game is starting.
    @Environment(\.isEnabled) private var isEnabled

    /// 0 with the lid shut over the holder (the box art shows), -180 with the lid open on the left (its inside shows).
    @State private var lidAngle: Double = 0
    /// The lid shows its inside. Switched as the lid passes upright, so each face shows only on its side.
    @State private var lidInside = false
    /// 0 shut, 1 open: a shut case sits in the middle of the screen, an open one has its spine there.
    @State private var spread: CGFloat = 0
    @State private var shown = false
    @State private var cart: CartPlace = .holder
    @State private var slotLit = false
    @State private var starting = false
    /// An animation runs: the buttons wait for it.
    @State private var busy = true
    @State private var closing = false
    @State private var launched = false
    @State private var hostTookOver = false
    @State private var clicks = 0

    enum CartPlace: Equatable { case holder, lifted, belowSlot, inSlot }

    private var game: GameTile { detail.game }

    var body: some View {
        GeometryReader { geometry in
            let m = Metrics(size: geometry.size)
            ZStack(alignment: .topLeading) {
                CoverFlowBackdrop(game: game)
                Color.black.opacity(0.5).ignoresSafeArea()

                slot(m)
                caseBody(m)
                    .scaleEffect(shown ? 1 : 0.86)
                    .opacity(shown ? 1 : 0)
                cartridge(m)
                header
                footer(m)

                if starting {
                    ZStack {
                        Color.black.ignoresSafeArea()
                        VStack(spacing: 14) {
                            ProgressView().tint(ShellPalette.cream)
                            Text(ShellStrings.text("Starting…")).shellText(14, .medium).foregroundStyle(.white.opacity(0.7))
                        }
                    }
                    .transition(.opacity)
                }
            }
            .frame(width: geometry.size.width, height: geometry.size.height)
        }
        .sensoryFeedback(.impact(weight: .heavy), trigger: clicks)
        .sensoryFeedback(.impact(weight: .light), trigger: lidInside)
        .task { await open() }
        .onChange(of: command) { _, new in
            switch new.kind {
            case .insert: Task { await insert() }
            case .close: Task { await close() }
            case .none: break
            }
        }
        .onChange(of: isEnabled) { _, enabled in
            guard launched else { return }
            if !enabled { hostTookOver = true } else { Task { await close(fast: true) } }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("case.\(game.id)")
    }

    // MARK: Layout

    /// Where everything goes, from the space the library gives the case.
    struct Metrics {
        let size: CGSize
        var compact: Bool { size.height < 500 }
        var top: CGFloat { compact ? 58 : 86 }
        var bottom: CGFloat { compact ? 62 : 96 }
        var halfHeight: CGFloat { max(120, min(size.height - top - bottom - 12, size.width * 0.78 / 2 / GameBoxArt.aspect)) }
        var halfWidth: CGFloat { halfHeight * GameBoxArt.aspect }
        /// The spine of the open case.
        var spine: CGPoint { CGPoint(x: size.width / 2, y: top + (size.height - top - bottom) / 2) }
        var holder: CGPoint { CGPoint(x: spine.x + halfWidth / 2, y: spine.y) }
        var cartWidth: CGFloat { halfWidth * 0.36 }
        var cartHeight: CGFloat { cartWidth / 0.76 }
        var cartInHolder: CGPoint { CGPoint(x: holder.x, y: holder.y + halfHeight * 0.17) }
        /// The console's slot: in the margin right of the case when there is room, else above the holder.
        var slot: CGPoint {
            let margin = size.width - (spine.x + halfWidth)
            if margin > cartWidth * 1.7 {
                return CGPoint(x: spine.x + halfWidth + margin / 2, y: spine.y - halfHeight * 0.36)
            }
            return CGPoint(x: holder.x, y: max(top * 0.5 + 14, spine.y - halfHeight / 2 - cartHeight * 0.55))
        }
    }

    private func caseBody(_ m: Metrics) -> some View {
        let shift = (spread - 1) * m.halfWidth / 2
        return ZStack(alignment: .topLeading) {
            CaseHolder(cartWidth: m.cartWidth, cartHeight: m.cartHeight, recessY: 0.5 + 0.17)
                .frame(width: m.halfWidth, height: m.halfHeight)
                .position(m.holder)
            lid(m)
                .frame(width: m.halfWidth, height: m.halfHeight)
                .rotation3DEffect(.degrees(reduceMotion ? (lidInside ? -180 : 0) : lidAngle),
                                  axis: (x: 0, y: 1, z: 0), anchor: .leading, perspective: 0.45)
                .position(m.holder)
        }
        .offset(x: shift)
        .shadow(color: .black.opacity(0.55), radius: 26, y: 14)
    }

    @ViewBuilder private func lid(_ m: Metrics) -> some View {
        if lidInside {
            // Drawn as it reads when open, then mirrored: the lid's half turn mirrors it back.
            LidInside(game: game, manual: ShellStrings.text("Manual").uppercased())
                .scaleEffect(x: -1, y: 1)
        } else {
            GameBoxArt(game: game, cornerRadius: m.halfWidth * 0.045)
                .overlay(RoundedRectangle(cornerRadius: m.halfWidth * 0.045).stroke(CaseColors.plastic, lineWidth: max(2, m.halfWidth * 0.025)))
        }
    }

    private func cartCenter(_ m: Metrics) -> CGPoint {
        let shift = (spread - 1) * m.halfWidth / 2
        switch cart {
        case .holder: return CGPoint(x: m.cartInHolder.x + shift, y: m.cartInHolder.y)
        case .lifted: return CGPoint(x: m.cartInHolder.x + shift, y: m.cartInHolder.y - m.cartHeight * 0.28)
        case .belowSlot: return CGPoint(x: m.slot.x, y: m.slot.y + m.cartHeight / 2 + 12)
        case .inSlot: return CGPoint(x: m.slot.x, y: m.slot.y + m.cartHeight / 2 - 2)
        }
    }

    private func cartridge(_ m: Metrics) -> some View {
        CartridgeView(game: game)
            .frame(width: m.cartWidth, height: m.cartHeight)
            .contentShape(Rectangle())
            .onTapGesture { Task { await insert() } }
            .accessibilityElement()
            .accessibilityLabel(ShellStrings.text("Cartridge"))
            .accessibilityAddTraits(.isButton)
            .accessibilityAction { Task { await insert() } }
            .scaleEffect(x: 1, y: cart == .inSlot ? 0.05 : 1, anchor: .top)
            .scaleEffect(cart == .lifted ? 1.14 : 1)
            .rotationEffect(.degrees(cart == .lifted ? -4 : 0))
            .shadow(color: .black.opacity(cart == .holder ? 0.35 : 0.6), radius: cart == .holder ? 3 : 14, y: cart == .holder ? 1 : 8)
            .opacity(lidInside && shown && cart != .inSlot ? 1 : 0)
            .allowsHitTesting(lidInside && cart == .holder && !busy)
            .position(cartCenter(m))
    }

    private func slot(_ m: Metrics) -> some View {
        let width = m.cartWidth * 1.25
        let height = max(8, m.cartWidth * 0.16)
        return HStack(spacing: 10) {
            Capsule()
                .fill(LinearGradient(colors: [Color(white: 0.02), Color(white: 0.10)], startPoint: .top, endPoint: .bottom))
                .overlay(Capsule().stroke(.white.opacity(0.22), lineWidth: 1))
                .overlay(Capsule().fill(ShellPalette.cream.opacity(slotLit ? 0.25 : 0)).blur(radius: 3))
                .frame(width: width, height: height)
            Circle()
                .fill(slotLit ? ShellPalette.ready : Color(white: 0.25))
                .frame(width: 7, height: 7)
                .shadow(color: slotLit ? ShellPalette.ready : .clear, radius: 6)
        }
        // The slot is centred on the cartridge's path, the light sits beside it.
        .offset(x: 8.5)
        .position(m.slot)
        .opacity(shown ? 1 : 0)
        .accessibilityHidden(true)
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 16) {
            VStack(alignment: .leading, spacing: 4) {
                Text(game.title).shellText(15, .semibold).lineLimit(1)
                Text(statsLine).shellText(12, .medium, relativeTo: .caption)
                    .foregroundStyle(.white.opacity(0.55)).lineLimit(1)
            }
            Spacer(minLength: 12)
            Button { Task { await close() } } label: {
                Label(ShellStrings.text("Close"), systemImage: "xmark")
            }
            .buttonStyle(ChipButtonStyle())
            .disabled(busy)
            .accessibilityIdentifier("case.close")
        }
        .padding(.horizontal, 20)
        .padding(.top, 8)
        .frame(maxWidth: .infinity, alignment: .top)
        .opacity(starting ? 0 : 1)
    }

    private func footer(_ m: Metrics) -> some View {
        ViewThatFits(in: .horizontal) {
            footerButtons(labels: true)
            footerButtons(labels: false)
        }
        .padding(.horizontal, 20)
        .padding(.bottom, m.compact ? 6 : 18)
        .frame(width: m.size.width, height: m.size.height, alignment: .bottom)
        .opacity(starting ? 0 : 1)
    }

    private func footerButtons(labels: Bool) -> some View {
        HStack(spacing: 12) {
            footerButton(ShellStrings.text("Insert cartridge"), role: .activate, label: true, id: "case.insert") { Task { await insert() } }
                .disabled(busy || game.state != .playable)
            footerButton(ShellStrings.text("Close the case"), symbol: "arrow.uturn.backward", label: labels, id: "case.closeBox") { Task { await close() } }
                .disabled(busy)
            footerButton(ShellStrings.text("Game info"), symbol: "info.circle", label: labels, id: "case.info") { info() }
                .disabled(busy)
            footerButton(ShellStrings.text("Back"), role: .back, label: labels, id: "case.back") { Task { await close() } }
                .disabled(busy)
        }
        .fixedSize()
    }

    private func footerButton(_ title: String, role: GlyphRole? = nil, symbol: String? = nil, label: Bool, id: String,
                              action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 8) {
                if let role { ButtonGlyph(role: role) }
                if let symbol { Image(systemName: symbol) }
                if label { Text(title).lineLimit(1) }
            }
        }
        .buttonStyle(ChipButtonStyle())
        .accessibilityLabel(title)
        .accessibilityIdentifier(id)
    }

    /// "Play time 5 min · Played today · Launches 2", or Not played yet.
    private var statsLine: String {
        var parts: [String] = []
        if game.playSeconds > 0 { parts.append(ShellStrings.text("Play time \(Self.duration(game.playSeconds))")) }
        if let recent = game.recentlyPlayed, !recent.isEmpty { parts.append(recent) }
        if game.launches > 0 { parts.append(ShellStrings.text("Launches \(game.launches)")) }
        if parts.isEmpty { parts.append(ShellStrings.text("Not played yet")) }
        return parts.joined(separator: " · ")
    }

    static func duration(_ seconds: Int) -> String {
        let formatter = DateComponentsFormatter()
        formatter.unitsStyle = .short
        formatter.allowedUnits = seconds >= 3600 ? [.hour, .minute] : [.minute]
        return formatter.string(from: TimeInterval(max(60, seconds))) ?? ""
    }

    // MARK: The animation

    private func pause(_ seconds: Double) async {
        try? await Task.sleep(for: .seconds(seconds))
    }

    private func open() async {
        guard !lidInside, !closing else { return }
        busy = true
        if reduceMotion {
            shown = true; lidInside = true; spread = 1; lidAngle = -180; busy = false
            return
        }
        withAnimation(.spring(duration: 0.4, bounce: 0.18)) { shown = true }
        await pause(0.35)
        guard !closing else { return }
        CartridgeSounds.shared.play(.open)
        withAnimation(.easeIn(duration: 0.2)) { lidAngle = -90; spread = 0.5 }
        await pause(0.2)
        guard !closing else { return }
        lidInside = true
        withAnimation(.spring(duration: 0.45, bounce: 0.22)) { lidAngle = -180; spread = 1 }
        await pause(0.3)
        busy = false
    }

    private func insert() async {
        guard !busy, !closing, !launched, lidInside, game.state == .playable else { return }
        busy = true
        CartridgeSounds.shared.play(.lift)
        withAnimation(reduceMotion ? nil : .spring(duration: 0.3, bounce: 0.3)) { cart = .lifted }
        await pause(reduceMotion ? 0.05 : 0.28)
        withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.5)) { cart = .belowSlot }
        await pause(reduceMotion ? 0.05 : 0.52)
        withAnimation(reduceMotion ? nil : .easeIn(duration: 0.14)) { cart = .inSlot }
        await pause(0.14)
        CartridgeSounds.shared.play(.click)
        clicks += 1
        withAnimation(.easeOut(duration: 0.25)) { slotLit = true }
        await pause(0.55)
        withAnimation(.easeIn(duration: 0.35)) { starting = true }
        await pause(0.35)
        launched = true
        launch()
        // A game that starts takes the screen (the host disables the library while it prepares it). When nothing took
        // over, the host said no (no data, a notice): back to the library.
        await pause(2.5)
        if !hostTookOver { await close(fast: true) }
    }

    private func close(fast: Bool = false) async {
        guard !closing else { return }
        // Never while the cartridge travels: it is in the slot or about to be.
        guard fast || cart == .holder else { return }
        closing = true
        busy = true
        if fast || reduceMotion || !lidInside {
            withAnimation(.easeOut(duration: 0.22)) { shown = false }
            await pause(0.22)
            closed()
            return
        }
        withAnimation(.easeIn(duration: 0.2)) { lidAngle = -90; spread = 0.5 }
        await pause(0.2)
        lidInside = false
        withAnimation(.easeOut(duration: 0.2)) { lidAngle = 0; spread = 0 }
        await pause(0.18)
        CartridgeSounds.shared.play(.close)
        await pause(0.14)
        withAnimation(.easeIn(duration: 0.22)) { shown = false }
        await pause(0.22)
        closed()
    }
}

/// The case's red plastic.
enum CaseColors {
    static let plastic = Color(red: 0.80, green: 0.06, blue: 0.10)
    static let deep = Color(red: 0.52, green: 0.02, blue: 0.05)
    static let panel = Color(red: 0.72, green: 0.04, blue: 0.08)
}

/// One half of the open case: the moulded plastic, its raised rim and the flat panel inside it.
struct CaseHalf: View {
    var body: some View {
        GeometryReader { geometry in
            let w = geometry.size.width
            let radius = w * 0.045
            ZStack {
                RoundedRectangle(cornerRadius: radius)
                    .fill(LinearGradient(colors: [CaseColors.plastic, CaseColors.deep], startPoint: .topLeading, endPoint: .bottomTrailing))
                RoundedRectangle(cornerRadius: radius * 0.7)
                    .fill(CaseColors.panel)
                    .overlay(RoundedRectangle(cornerRadius: radius * 0.7).stroke(.black.opacity(0.28), lineWidth: max(1, w * 0.012)))
                    .overlay(RoundedRectangle(cornerRadius: radius * 0.7).stroke(.white.opacity(0.10), lineWidth: 1).padding(1.5))
                    .padding(w * 0.045)
            }
        }
    }
}

/// The right half: the panel with the recess the cartridge sits in.
struct CaseHolder: View {
    let cartWidth: CGFloat
    let cartHeight: CGFloat
    /// The recess's centre, as a fraction of the half's height.
    let recessY: CGFloat
    var body: some View {
        GeometryReader { geometry in
            ZStack {
                CaseHalf()
                RoundedRectangle(cornerRadius: cartWidth * 0.1)
                    .fill(CaseColors.deep)
                    .overlay(RoundedRectangle(cornerRadius: cartWidth * 0.1).stroke(.black.opacity(0.45), lineWidth: 2))
                    .frame(width: cartWidth * 1.12, height: cartHeight * 1.08)
                    .position(x: geometry.size.width / 2, y: geometry.size.height * recessY)
            }
        }
        .accessibilityHidden(true)
    }
}

/// The lid's inside as it reads when open: the manual, its front the box art, held by two clips on the spine side.
struct LidInside: View {
    let game: GameTile
    let manual: String
    var body: some View {
        GeometryReader { geometry in
            let w = geometry.size.width
            let h = geometry.size.height
            ZStack {
                CaseHalf()
                VStack(spacing: 0) {
                    Group {
                        if let cover = game.cover {
                            Image(decorative: cover.image, scale: 1).resizable().interpolation(.high).scaledToFill()
                        } else {
                            ArtView(game: game, lettering: false)
                        }
                    }
                    .frame(width: w * 0.80, height: h * 0.78)
                    .clipped()
                    HStack {
                        Text(manual).font(ShellFonts.fixed(max(6, w * 0.045), weight: .bold)).tracking(w * 0.004)
                        Spacer(minLength: 4)
                        Image(systemName: "book.closed.fill").font(.system(size: max(6, w * 0.045)))
                    }
                    .foregroundStyle(Color(white: 0.2))
                    .padding(.horizontal, w * 0.04)
                    .frame(width: w * 0.80, height: h * 0.06)
                    .background(Color(white: 0.95))
                }
                .clipShape(RoundedRectangle(cornerRadius: w * 0.015))
                .shadow(color: .black.opacity(0.35), radius: 4, y: 2)
                // The clips on the spine side.
                ForEach([CGFloat(0.3), CGFloat(0.7)], id: \.self) { y in
                    RoundedRectangle(cornerRadius: w * 0.02)
                        .fill(LinearGradient(colors: [CaseColors.plastic, CaseColors.deep], startPoint: .leading, endPoint: .trailing))
                        .frame(width: w * 0.07, height: h * 0.09)
                        .position(x: w * 0.92, y: h * y)
                        .shadow(color: .black.opacity(0.3), radius: 2, x: -1)
                }
            }
        }
        .accessibilityHidden(true)
    }
}
