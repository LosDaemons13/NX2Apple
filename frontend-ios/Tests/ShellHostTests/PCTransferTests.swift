import Foundation
import Testing
@testable import ShellHost

/// Answers the share's addresses from a table, as the Windows launcher's wifi_share.py would.
final class FakeShare: URLProtocol {
    nonisolated(unsafe) static var files: [String: (Int, Data)] = [:]
    nonisolated(unsafe) static var asked: [String] = []

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let path = request.url?.path ?? ""
        Self.asked.append(path)
        let (status, body) = Self.files[path] ?? (404, Data("not found".utf8))
        let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: "HTTP/1.1",
                                       headerFields: ["Content-Length": "\(body.count)"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: body)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}

    static func configuration() -> URLSessionConfiguration {
        let c = URLSessionConfiguration.ephemeral
        c.protocolClasses = [FakeShare.self]
        return c
    }
}

@MainActor @Suite(.serialized) struct PCTransferTests {
    let tid = "0100000000010000"

    @Test func theAddressTakesWhatThePlayerTypes() {
        #expect(PCAddress.base(from: "192.168.1.20:8765/abc234")?.absoluteString == "http://192.168.1.20:8765/abc234/")
        #expect(PCAddress.base(from: " http://192.168.1.20:8765/abc234/ ")?.absoluteString == "http://192.168.1.20:8765/abc234/")
        #expect(PCAddress.base(from: "192.168.1.20:8765/abc234/NX2Apple.ipa")?.absoluteString == "http://192.168.1.20:8765/abc234/")
        #expect(PCAddress.base(from: "") == nil)
        #expect(PCAddress.base(from: "http://") == nil)
    }

    @Test func onlyWhatTheIPhoneLacksIsFetchedAndNothingOutsideTheGamesFolder() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("pcplan-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try Data(count: 10).write(to: root.appendingPathComponent("romfs.img.id"))
        try Data(count: 3).write(to: root.appendingPathComponent("romfs.img"))   // cut short earlier
        let game = PCGame(titleID: tid, name: "Mario", bytes: 0, files: [
            PCFile(path: "romfs.img", size: 100), PCFile(path: "romfs.img.id", size: 10),
            PCFile(path: "aoc/0100000000011001/romfs.img", size: 5), PCFile(path: "../escape", size: 1),
            PCFile(path: "/etc/passwd", size: 1)])
        #expect(PCTransferPlan.missing(game, in: root).map(\.path) == ["romfs.img", "aoc/0100000000011001/romfs.img"])
    }

    @Test func theGamesDataArrivesInTheAppsFolderAndTheLibraryLooksAgain() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("pcrecv-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let image = Data((0..<4096).map { UInt8($0 % 251) })
        let catalog = """
        {"version": 1, "ipa": null, "games": [
          {"title_id": "\(tid)", "name": "Super Mario Odyssey", "bytes": 4106, "files": [
            {"path": "aoc/0100000000011001/romfs.img", "size": 6}, {"path": "romfs.img", "size": 4096},
            {"path": "romfs.img.id", "size": 4}]},
          {"title_id": "0100000000020000", "name": "Not in the app", "bytes": 1, "files": [{"path": "romfs.img", "size": 1}]}]}
        """
        FakeShare.asked = []
        FakeShare.files = [
            "/abc234/catalog.json": (200, Data(catalog.utf8)),
            "/abc234/games/\(tid)/romfs.img": (200, image),
            "/abc234/games/\(tid)/romfs.img.id": (200, Data("{id}".utf8)),
            "/abc234/games/\(tid)/aoc/0100000000011001/romfs.img": (200, Data("DLCDLC".utf8)),
        ]
        let defaults = UserDefaults(suiteName: "pc.\(UUID().uuidString)")!
        let finished = LogBox()
        let r = PCReceiver(appDataRoot: root, installedIDs: [tid], defaults: defaults, configuration: FakeShare.configuration(),
                           onFinished: { finished.add("finished") })
        r.address = "192.168.1.20:8765/abc234"
        await r.connectNow()
        #expect(r.phase == .listed)
        #expect(r.rows.map(\.selected) == [true, false], "games in the app with data missing are ticked")
        #expect(r.rows.map(\.installed) == [true, false])
        #expect(r.selectedBytes == 4106)
        #expect(defaults.string(forKey: PCReceiver.addressKey) == "192.168.1.20:8765/abc234", "the address is remembered")

        await r.receiveNow()
        #expect(r.phase == .done)
        let folder = root.appendingPathComponent(tid, isDirectory: true)
        #expect(try Data(contentsOf: folder.appendingPathComponent("romfs.img")) == image)
        #expect(try Data(contentsOf: folder.appendingPathComponent("aoc/0100000000011001/romfs.img")) == Data("DLCDLC".utf8))
        #expect(!FileManager.default.fileExists(atPath: folder.appendingPathComponent("romfs.img.download").path))
        #expect(r.rows[0].missing.isEmpty && !r.rows[0].selected)
        #expect(finished.all.count == 1)
        #expect(r.allDone == r.allTotal)

        FakeShare.asked = []
        await r.connectNow()
        #expect(r.rows[0].missing.isEmpty, "a second visit fetches nothing again")
        #expect(FakeShare.asked == ["/abc234/catalog.json"])
    }

    @Test func aWrongAddressSaysSoInsteadOfFailingQuietly() async {
        FakeShare.files = [:]
        let r = PCReceiver(appDataRoot: FileManager.default.temporaryDirectory, installedIDs: [],
                           defaults: UserDefaults(suiteName: "pc.\(UUID().uuidString)")!, configuration: FakeShare.configuration())
        r.address = "192.168.1.20:8765/wrong1"
        await r.connectNow()
        #expect(r.phase == .failed(PCTransferError.notAShare.localizedDescription))
        r.address = "   "
        await r.connectNow()
        #expect(r.phase == .failed(PCTransferError.badAddress.localizedDescription))
    }
}
