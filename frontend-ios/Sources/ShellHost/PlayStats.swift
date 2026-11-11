import Foundation

/// How long and how often a game was played in this app, in the game's own defaults suite beside `shell.lastPlayed`.
/// Separate keys from the `launcher.<VAR>` choices, so Reset to tested defaults keeps them.
public struct PlayStatsStore {
    public static let secondsKey = "shell.playSeconds"
    public static let launchesKey = "shell.launches"
    private let defaults: UserDefaults
    public init(defaults: UserDefaults) { self.defaults = defaults }
    public var seconds: Int { defaults.integer(forKey: Self.secondsKey) }
    public var launches: Int { defaults.integer(forKey: Self.launchesKey) }
    public func recordLaunch() { defaults.set(launches + 1, forKey: Self.launchesKey) }
    public func add(seconds: Int) { defaults.set(self.seconds + seconds, forKey: Self.secondsKey) }
}

/// Counts play time while a game runs. The engine takes the process over once a game starts, and quitting a game closes
/// the app, so nothing tells the shell when a game ends: a timer on a background queue adds the time in steps instead.
/// Whatever ends the game, at most one step is lost. A suspended app does not count.
public enum PlayClock {
    static let step = 20
    nonisolated(unsafe) private static var timer: DispatchSourceTimer?

    public static func start(id: String, defaults: @escaping @Sendable (String) -> UserDefaults) {
        timer?.cancel()
        let source = DispatchSource.makeTimerSource(queue: .global(qos: .utility))
        source.schedule(deadline: .now() + .seconds(step), repeating: .seconds(step))
        source.setEventHandler { PlayStatsStore(defaults: defaults(id)).add(seconds: step) }
        source.resume()
        timer = source
    }

    /// The game did not start after all.
    public static func stop() {
        timer?.cancel()
        timer = nil
    }
}
