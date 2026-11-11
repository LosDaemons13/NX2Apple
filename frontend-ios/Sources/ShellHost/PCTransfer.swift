import Foundation
import Observation
#if canImport(UIKit)
import UIKit
#endif

/// "Receive from PC": the Windows launcher serves each built game's data folder on the home Wi-Fi (frontend-qt
/// nspb_qt/wifi_share.py) at `http://<PC>:<port>/<code>/`, and this fetches what the iPhone lacks straight into the app's
/// `Documents/games/<title ID>/`, where `DataLocator` finds it. No Files app, no cable, nothing through the internet.
///
/// The PC lists, per game, the regular files of its data folder (`romfs.img`, `romfs.img.id`, `aoc/…`) with their sizes
/// (`catalog.json`). A file the iPhone already has at that size is kept; the others come one at a time, each to a
/// `.download` file renamed into place when it is whole, so an interrupted transfer never leaves a short image where a
/// game looks for its data.
public enum PCAddress {
    /// The share's base URL from what the player typed: `192.168.1.20:8765/abc234`, with or without `http://`, a trailing
    /// slash or the page's own name. Nil when it names no host.
    public static func base(from text: String) -> URL? {
        var s = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !s.isEmpty else { return nil }
        if !s.lowercased().hasPrefix("http://") && !s.lowercased().hasPrefix("https://") { s = "http://" + s }
        for tail in ["/catalog.json", "/index.html", "/NX2Apple.ipa"] where s.hasSuffix(tail) { s.removeLast(tail.count) }
        if !s.hasSuffix("/") { s += "/" }
        guard let url = URL(string: s), let host = url.host, !host.isEmpty else { return nil }
        return url
    }

    /// The share's address in a pasted text, which may be a whole message ("Adresse : 192.168.1.20:8765/abc234"): the
    /// first word that names a port, else the text itself.
    public static func find(in text: String) -> String {
        let words = text.split(whereSeparator: \.isWhitespace).map(String.init)
        return words.first { base(from: $0)?.port != nil } ?? text.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

public struct PCFile: Decodable, Equatable, Sendable {
    public var path: String
    public var size: Int64
}

public struct PCGame: Decodable, Equatable, Sendable, Identifiable {
    public var titleID: String
    public var name: String
    public var bytes: Int64
    public var files: [PCFile]
    public var id: String { titleID }
    enum CodingKeys: String, CodingKey { case titleID = "title_id", name, bytes, files }
}

public struct PCCatalog: Decodable, Equatable, Sendable {
    public var version: Int
    public var games: [PCGame]
}

public enum PCTransferPlan {
    /// The files of `game` the iPhone does not have at the PC's size, under `folder` (the game's `Documents/games/<id>/`).
    /// A path that would leave the folder is never taken.
    public static func missing(_ game: PCGame, in folder: URL, fileManager fm: FileManager = .default) -> [PCFile] {
        game.files.filter { file in
            guard isSafe(file.path) else { return false }
            let local = folder.appendingPathComponent(file.path)
            let size = (try? fm.attributesOfItem(atPath: local.path)[.size] as? NSNumber)?.int64Value
            return size != file.size
        }
    }

    static func isSafe(_ path: String) -> Bool {
        !path.isEmpty && !path.hasPrefix("/") && !path.contains("\\") && !path.split(separator: "/").contains("..")
            && !path.split(separator: "/").contains(".")
    }

    /// Bytes still to fetch for `games`.
    public static func bytes(_ files: [PCFile]) -> Int64 { files.reduce(0) { $0 + $1.size } }
}

/// One file over URLSession's download task, with its progress. The finished temporary file is moved to `destination`
/// before the delegate returns (the system deletes it after), through `destination.download` and a rename.
final class PCFileFetcher: NSObject, URLSessionDownloadDelegate, @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<Void, any Error>?
    private var moveError: (any Error)?
    private let destination: URL
    private let progress: @Sendable (Int64, Int64) -> Void
    private let configuration: URLSessionConfiguration
    private var session: URLSession?

    init(destination: URL, configuration: URLSessionConfiguration = .default, progress: @escaping @Sendable (Int64, Int64) -> Void) {
        self.destination = destination
        // a copy of its own: the transfer's timeouts are set on it, not on the caller's
        self.configuration = (configuration.copy() as? URLSessionConfiguration) ?? .default
        self.progress = progress
    }

    func fetch(_ url: URL) async throws {
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { (c: CheckedContinuation<Void, any Error>) in
                lock.lock(); continuation = c; lock.unlock()
                configuration.timeoutIntervalForRequest = 60
                configuration.timeoutIntervalForResource = 24 * 3600
                let s = URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
                lock.lock(); session = s; lock.unlock()
                s.downloadTask(with: url).resume()
            }
        } onCancel: {
            lock.lock(); let s = session; lock.unlock()
            s?.invalidateAndCancel()
        }
    }

    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didWriteData bytesWritten: Int64,
                    totalBytesWritten: Int64, totalBytesExpectedToWrite: Int64) {
        progress(totalBytesWritten, totalBytesExpectedToWrite)
    }

    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {
        let status = (downloadTask.response as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200 else { lock.lock(); moveError = PCTransferError.http(status); lock.unlock(); return }
        let fm = FileManager.default
        let partial = destination.appendingPathExtension("download")
        do {
            try fm.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
            try? fm.removeItem(at: partial)
            try fm.moveItem(at: location, to: partial)
            if fm.fileExists(atPath: destination.path) {
                _ = try fm.replaceItemAt(destination, withItemAt: partial)
            } else {
                try fm.moveItem(at: partial, to: destination)
            }
        } catch {
            try? fm.removeItem(at: partial)
            lock.lock(); moveError = error; lock.unlock()
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: (any Error)?) {
        lock.lock()
        let c = continuation; continuation = nil
        let failure = error ?? moveError
        lock.unlock()
        session.finishTasksAndInvalidate()
        if let failure { c?.resume(throwing: failure) } else { c?.resume() }
    }
}

public enum PCTransferError: Error, Equatable, LocalizedError {
    case badAddress, http(Int), notAShare, noSpace(needed: Int64, free: Int64)
    public var errorDescription: String? {
        switch self {
        case .badAddress: hostText("That address is not one the PC shows. It looks like 192.168.1.20:8765/abc234.")
        case .http(let code): hostText("The PC answered with an error (\(code)). Check the address in the launcher's Send to iPhone window.")
        case .notAShare: hostText("That address is not NX2Apple's share on the PC.")
        case .noSpace(let needed, let free):
            hostText("Not enough space on this iPhone: \(ByteCountFormatter.string(fromByteCount: needed, countStyle: .file)) needed, \(ByteCountFormatter.string(fromByteCount: free, countStyle: .file)) free.")
        }
    }
}

/// The "Receive from PC" screen's state: the address, what the PC offers, and the transfer.
@MainActor @Observable public final class PCReceiver {
    public enum Phase: Equatable { case idle, connecting, listed, receiving, done, failed(String) }

    public struct Row: Identifiable, Equatable {
        public var game: PCGame
        public var missing: [PCFile]
        public var installed: Bool              // the game is in this app (its framework is in the IPA)
        public var selected: Bool
        public var id: String { game.titleID }
        public var bytesToFetch: Int64 { PCTransferPlan.bytes(missing) }
    }

    public var address: String
    public private(set) var phase: Phase = .idle
    public private(set) var rows: [Row] = []
    /// The file being fetched, and its bytes done / total.
    public private(set) var current: String = ""
    public private(set) var fileDone: Int64 = 0
    public private(set) var fileTotal: Int64 = 0
    public private(set) var allDone: Int64 = 0
    public private(set) var allTotal: Int64 = 0

    @ObservationIgnored private let appDataRoot: URL
    @ObservationIgnored private let installedIDs: Set<String>
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let configuration: URLSessionConfiguration
    @ObservationIgnored private let onFinished: @MainActor () -> Void
    @ObservationIgnored private var task: Task<Void, Never>?
    static let addressKey = "shell.pcShareAddress"

    public init(appDataRoot: URL, installedIDs: Set<String>, defaults: UserDefaults = .standard,
                configuration: URLSessionConfiguration = .default, onFinished: @escaping @MainActor () -> Void = {}) {
        self.appDataRoot = appDataRoot
        self.installedIDs = installedIDs
        self.defaults = defaults
        self.configuration = configuration
        self.onFinished = onFinished
        address = defaults.string(forKey: Self.addressKey) ?? ""
    }

    public func connect() {
        task?.cancel()
        task = Task { await connectNow() }
    }

    /// The screen's Paste button: the address in the pasted text replaces what was typed, and the screen connects to it.
    public func paste(_ text: String) {
        address = PCAddress.find(in: text)
        connect()
    }

    func connectNow() async {
        guard let base = PCAddress.base(from: address) else { phase = .failed(PCTransferError.badAddress.localizedDescription); return }
        phase = .connecting
        do {
            let (data, response) = try await URLSession(configuration: configuration).data(from: base.appendingPathComponent("catalog.json"))
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            guard code == 200 else { throw code == 404 ? PCTransferError.notAShare : PCTransferError.http(code) }
            guard let catalog = try? JSONDecoder().decode(PCCatalog.self, from: data), catalog.version >= 1 else { throw PCTransferError.notAShare }
            defaults.set(address, forKey: Self.addressKey)
            rows = catalog.games.map { game in
                let missing = PCTransferPlan.missing(game, in: folder(game.titleID))
                let installed = installedIDs.contains(game.titleID.uppercased())
                return Row(game: game, missing: missing, installed: installed, selected: installed && !missing.isEmpty)
            }
            phase = .listed
        } catch is CancellationError {
            phase = .idle
        } catch {
            phase = .failed(error.localizedDescription)
        }
    }

    public func toggle(_ id: String) {
        guard let i = rows.firstIndex(where: { $0.id == id }), !rows[i].missing.isEmpty else { return }
        rows[i].selected.toggle()
    }

    public var selectedBytes: Int64 { rows.filter(\.selected).reduce(0) { $0 + $1.bytesToFetch } }

    public func receive() {
        task?.cancel()
        task = Task { await receiveNow() }
    }

    public func cancel() {
        task?.cancel()
        task = nil
        setIdleTimer(false)
        if phase == .receiving || phase == .connecting { phase = rows.isEmpty ? .idle : .listed }
    }

    func receiveNow() async {
        guard let base = PCAddress.base(from: address) else { phase = .failed(PCTransferError.badAddress.localizedDescription); return }
        let chosen = rows.filter(\.selected)
        let needed = chosen.reduce(0) { $0 + $1.bytesToFetch }
        if let free = freeSpace(), free < needed { phase = .failed(PCTransferError.noSpace(needed: needed, free: free).localizedDescription); return }
        phase = .receiving
        allTotal = needed
        allDone = 0
        setIdleTimer(true)   // the screen stays on: a locked iPhone stops the transfer
        defer { setIdleTimer(false) }
        do {
            for row in chosen {
                for file in row.missing {
                    try Task.checkCancellation()
                    current = "\(row.game.name) · \(file.path)"
                    fileDone = 0
                    fileTotal = file.size
                    let before = allDone
                    let url = base.appendingPathComponent("games").appendingPathComponent(row.game.titleID).appendingPathComponent(file.path)
                    let fetcher = PCFileFetcher(destination: folder(row.game.titleID).appendingPathComponent(file.path),
                                                configuration: configuration) { [weak self] done, _ in
                        Task { @MainActor [weak self] in
                            self?.fileDone = done
                            self?.allDone = before + done
                        }
                    }
                    try await fetcher.fetch(url)
                    allDone = before + file.size
                }
                if let i = rows.firstIndex(where: { $0.id == row.id }) {
                    rows[i].missing = PCTransferPlan.missing(row.game, in: folder(row.game.titleID))
                    rows[i].selected = false
                }
            }
            current = ""
            phase = .done
            onFinished()
        } catch is CancellationError {
            phase = .listed
        } catch {
            phase = .failed(error.localizedDescription)
            onFinished()   // what did arrive is in place: the library looks again
        }
    }

    private func folder(_ id: String) -> URL { appDataRoot.appendingPathComponent(id.uppercased(), isDirectory: true) }

    private func freeSpace() -> Int64? {
        let root = appDataRoot.deletingLastPathComponent()
        let values = try? root.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey])
        return values?.volumeAvailableCapacityForImportantUsage
    }

    private func setIdleTimer(_ on: Bool) {
        #if canImport(UIKit)
        UIApplication.shared.isIdleTimerDisabled = on
        #endif
    }
}
