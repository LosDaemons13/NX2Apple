import SwiftUI

/// A game's case seen from the front, as it stands on a shelf: the box art the player chose on the PC (`cover.<ext>` in the
/// game's framework), else the key art cut to the case's shape with the title set at the bottom. A clear sleeve's sheen and
/// a thin plastic rim make it read as a box rather than a picture.
struct GameBoxArt: View {
    /// A game case is about 105 × 170 mm.
    nonisolated static let aspect: CGFloat = 0.62
    let game: GameTile
    var cornerRadius: CGFloat = 8
    var showsState = false

    var body: some View {
        GeometryReader { geometry in
            let size = geometry.size
            ZStack {
                artwork(size)
                // The clear sleeve over the printed cover: a soft diagonal sheen, brighter at the top.
                LinearGradient(stops: [.init(color: .white.opacity(0.20), location: 0),
                                       .init(color: .white.opacity(0.04), location: 0.32),
                                       .init(color: .clear, location: 0.55),
                                       .init(color: .white.opacity(0.07), location: 1)],
                               startPoint: .topLeading, endPoint: .bottomTrailing)
                    .blendMode(.screen)
                    .allowsHitTesting(false)
            }
            .frame(width: size.width, height: size.height)
            .clipShape(RoundedRectangle(cornerRadius: cornerRadius))
            .overlay(RoundedRectangle(cornerRadius: cornerRadius).strokeBorder(.white.opacity(0.30), lineWidth: max(1, size.width * 0.012)))
            .overlay(alignment: .topLeading) {
                if showsState {
                    let dot = max(8, min(14, size.width * 0.06))
                    Group {
                        if game.state.artworkWarning != nil {
                            AlertStateChip(state: game.state, dotSize: dot)
                        } else if game.state != .playable {
                            StateDot(state: game.state, size: dot)
                        }
                    }
                    .padding(dot * 0.8)
                }
            }
        }
        .aspectRatio(Self.aspect, contentMode: .fit)
        .saturation(game.state == .playable ? 1 : 0)
        .accessibilityHidden(true)
    }

    @ViewBuilder private func artwork(_ size: CGSize) -> some View {
        if let cover = game.cover {
            Image(decorative: cover.image, scale: 1).resizable().interpolation(.high).scaledToFill()
                .frame(width: size.width, height: size.height).clipped()
        } else {
            ZStack(alignment: .bottom) {
                ArtView(game: game, lettering: false)
                    .frame(width: size.width, height: size.height)
                LinearGradient(colors: [.clear, .black.opacity(0.82)], startPoint: .center, endPoint: .bottom)
                Text(game.title)
                    .font(ShellFonts.fixed(max(8, size.width * 0.095), weight: .heavy))
                    .tracking(-size.width * 0.002)
                    .foregroundStyle(.white)
                    .multilineTextAlignment(.center)
                    .lineLimit(3).minimumScaleFactor(0.6)
                    .shadow(color: .black.opacity(0.5), radius: 4)
                    .padding(.horizontal, size.width * 0.08)
                    .padding(.bottom, size.width * 0.10)
            }
            .frame(width: size.width, height: size.height)
        }
    }
}

/// The cartridge itself: dark plastic with one corner cut, the box art as its label and the title on a strip under it.
struct CartridgeView: View {
    let game: GameTile
    var body: some View {
        GeometryReader { geometry in
            let w = geometry.size.width
            let h = geometry.size.height
            let shell = UnevenRoundedRectangle(topLeadingRadius: w * 0.07, bottomLeadingRadius: w * 0.07,
                                               bottomTrailingRadius: w * 0.07, topTrailingRadius: w * 0.26)
            ZStack(alignment: .top) {
                shell.fill(LinearGradient(colors: [Color(white: 0.23), Color(white: 0.12)], startPoint: .top, endPoint: .bottom))
                shell.stroke(.white.opacity(0.16), lineWidth: max(0.5, w * 0.012))
                VStack(spacing: h * 0.025) {
                    label(width: w * 0.80, height: h * 0.62)
                    Text(game.title)
                        .font(ShellFonts.fixed(max(4, w * 0.065), weight: .semibold))
                        .foregroundStyle(.white.opacity(0.7))
                        .lineLimit(1).minimumScaleFactor(0.5)
                        .frame(width: w * 0.80)
                }
                .padding(.top, h * 0.09)
            }
            .frame(width: w, height: h)
        }
        .aspectRatio(0.76, contentMode: .fit)
        .accessibilityHidden(true)
    }

    @ViewBuilder private func label(width: CGFloat, height: CGFloat) -> some View {
        Group {
            if let cover = game.cover {
                Image(decorative: cover.image, scale: 1).resizable().interpolation(.high).scaledToFill()
            } else {
                ArtView(game: game, lettering: false)
            }
        }
        .frame(width: width, height: height)
        .clipShape(RoundedRectangle(cornerRadius: width * 0.05))
        .overlay(RoundedRectangle(cornerRadius: width * 0.05).strokeBorder(.white.opacity(0.18), lineWidth: 0.5))
    }
}

/// One dot per game, the selected one drawn as a short bar, as under the carousel on the console's home screen.
struct PageDots: View {
    let count: Int
    let index: Int
    /// Past this many games the dots would not fit under the card: a window of them follows the selection.
    var maximum = 9
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var body: some View {
        let shown = min(count, maximum)
        let first = max(0, min(count - shown, index - shown / 2))
        HStack(spacing: 7) {
            ForEach(first..<(first + shown), id: \.self) { i in
                Capsule()
                    .fill(.white.opacity(i == index ? 0.95 : 0.32))
                    .frame(width: i == index ? 18 : 6, height: 6)
            }
        }
        .animation(reduceMotion ? nil : .smooth(duration: 0.25), value: index)
        .frame(minHeight: 24)
        .accessibilityHidden(true)
    }
}
