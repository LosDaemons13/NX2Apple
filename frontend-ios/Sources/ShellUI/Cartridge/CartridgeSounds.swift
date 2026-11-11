import AVFoundation
import Foundation

/// A sound of the case or of the cartridge.
enum CartridgeCue: CaseIterable, Sendable {
    /// The latch lets go and the lid swings open.
    case open
    /// The lid swings back and snaps shut.
    case close
    /// The cartridge comes out of its holder.
    case lift
    /// The cartridge seats in the slot: the click.
    case click
}

/// The case's and the cartridge's sounds. They are synthesised once in memory, so no audio file ships with the shell.
/// The app's audio session is left as the system made it (solo ambient): the silent switch mutes them, and the engine
/// sets up its own session when the game starts.
@MainActor final class CartridgeSounds {
    static let shared = CartridgeSounds()

    private var players: [CartridgeCue: AVAudioPlayer] = [:]

    private init() {}

    func play(_ cue: CartridgeCue) {
        let player: AVAudioPlayer
        if let ready = players[cue] {
            player = ready
        } else {
            guard let made = try? AVAudioPlayer(data: CartridgeSynth.wav(CartridgeSynth.samples(for: cue))) else { return }
            made.prepareToPlay()
            players[cue] = made
            player = made
        }
        player.currentTime = 0
        player.play()
    }
}

/// The sounds' samples, mono at 44.1 kHz: noise bursts for the plastic, short decaying tones for its ring, a low thump for
/// the body. Deterministic, so every launch sounds the same.
enum CartridgeSynth {
    static let rate = 44_100

    static func samples(for cue: CartridgeCue) -> [Float] {
        switch cue {
        case .click:
            var s = silence(0.16)
            thump(&s, at: 0, frequency: 170, decay: 0.012, gain: 0.30)
            tick(&s, at: 0, noiseDecay: 0.0006, ring: 2900, ringDecay: 0.006, gain: 0.95)
            tone(&s, at: 0.001, frequency: 1700, decay: 0.010, gain: 0.25)
            tick(&s, at: 0.055, noiseDecay: 0.0005, ring: 2300, ringDecay: 0.005, gain: 0.55)
            return s
        case .open:
            var s = silence(0.34)
            tick(&s, at: 0, noiseDecay: 0.0005, ring: 3500, ringDecay: 0.004, gain: 0.45)
            whoosh(&s, from: 0.02, length: 0.16, gain: 0.07)
            thump(&s, at: 0.2, frequency: 140, decay: 0.025, gain: 0.32)
            tick(&s, at: 0.2, noiseDecay: 0.0012, ring: 1900, ringDecay: 0.006, gain: 0.25)
            return s
        case .close:
            var s = silence(0.30)
            whoosh(&s, from: 0, length: 0.14, gain: 0.06)
            thump(&s, at: 0.16, frequency: 150, decay: 0.02, gain: 0.35)
            tick(&s, at: 0.16, noiseDecay: 0.0007, ring: 3200, ringDecay: 0.006, gain: 0.85)
            tick(&s, at: 0.185, noiseDecay: 0.0005, ring: 2600, ringDecay: 0.004, gain: 0.35)
            return s
        case .lift:
            var s = silence(0.06)
            tick(&s, at: 0, noiseDecay: 0.0008, ring: 4200, ringDecay: 0.003, gain: 0.32)
            return s
        }
    }

    private static func silence(_ seconds: Double) -> [Float] { [Float](repeating: 0, count: Int(seconds * Double(rate))) }

    /// A deterministic white noise source, -1 to 1.
    private struct Noise {
        var state: UInt32 = 0x9E37_79B9
        mutating func next() -> Float {
            state = state &* 1_664_525 &+ 1_013_904_223
            return Float(Int32(bitPattern: state)) / Float(Int32.max)
        }
    }

    private static func tick(_ s: inout [Float], at start: Double, noiseDecay: Double, ring: Double, ringDecay: Double, gain: Float) {
        var noise = Noise()
        let first = Int(start * Double(rate))
        let length = Int(max(noiseDecay * 8, 0.004) * Double(rate))
        for i in 0..<length where first + i < s.count {
            let t = Double(i) / Double(rate)
            s[first + i] += noise.next() * gain * Float(exp(-t / noiseDecay))
        }
        tone(&s, at: start, frequency: ring, decay: ringDecay, gain: gain * 0.45)
    }

    private static func tone(_ s: inout [Float], at start: Double, frequency: Double, decay: Double, gain: Float) {
        let first = Int(start * Double(rate))
        let length = Int(decay * 7 * Double(rate))
        for i in 0..<length where first + i < s.count {
            let t = Double(i) / Double(rate)
            s[first + i] += gain * Float(sin(2 * Double.pi * frequency * t) * exp(-t / decay))
        }
    }

    private static func thump(_ s: inout [Float], at start: Double, frequency: Double, decay: Double, gain: Float) {
        let first = Int(start * Double(rate))
        let length = Int(decay * 6 * Double(rate))
        for i in 0..<length where first + i < s.count {
            let t = Double(i) / Double(rate)
            // The pitch drops a little as a body settles.
            let f = frequency * (1 - 0.3 * min(1, t / (decay * 6)))
            s[first + i] += gain * Float(sin(2 * Double.pi * f * t) * exp(-t / decay))
        }
    }

    /// Air moving with the lid: low-passed noise that swells and fades.
    private static func whoosh(_ s: inout [Float], from start: Double, length seconds: Double, gain: Float) {
        var noise = Noise(state: 0x1234_5678)
        let first = Int(start * Double(rate))
        let length = Int(seconds * Double(rate))
        var low: Float = 0
        for i in 0..<length where first + i < s.count {
            let phase = Double(i) / Double(max(1, length))
            low += 0.08 * (noise.next() - low)
            s[first + i] += low * gain * 4 * Float(sin(Double.pi * phase))
        }
    }

    /// 16-bit PCM WAV bytes, which AVAudioPlayer reads from memory.
    static func wav(_ samples: [Float]) -> Data {
        var data = Data()
        func u32(_ v: UInt32) { withUnsafeBytes(of: v.littleEndian) { data.append(contentsOf: $0) } }
        func u16(_ v: UInt16) { withUnsafeBytes(of: v.littleEndian) { data.append(contentsOf: $0) } }
        let payload = UInt32(samples.count * 2)
        data.append(contentsOf: Array("RIFF".utf8)); u32(36 + payload)
        data.append(contentsOf: Array("WAVE".utf8))
        data.append(contentsOf: Array("fmt ".utf8)); u32(16)
        u16(1); u16(1); u32(UInt32(rate)); u32(UInt32(rate * 2)); u16(2); u16(16)
        data.append(contentsOf: Array("data".utf8)); u32(payload)
        for sample in samples {
            let clipped = max(-1, min(1, sample))
            u16(UInt16(bitPattern: Int16(clipped * 32_767)))
        }
        return data
    }
}
