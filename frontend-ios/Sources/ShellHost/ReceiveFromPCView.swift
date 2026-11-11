import SwiftUI
import ShellUI
#if canImport(UIKit)
import UIKit
#endif

/// The "Receive from PC" screen (PCTransfer.swift): the address the launcher's Send to iPhone window shows, what the PC
/// offers, and the transfer.
struct ReceiveFromPCView: View {
    @Bindable var receiver: PCReceiver
    let onClose: () -> Void

    private func size(_ n: Int64) -> String { ByteCountFormatter.string(fromByteCount: n, countStyle: .file) }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField(text: $receiver.address, prompt: Text(verbatim: "192.168.1.20:8765/abc234")) {
                        Text(verbatim: hostText("PC address"))
                    }
                    .addressEntry()
                    .submitLabel(.go)
                    .onSubmit { receiver.connect() }
                    .disabled(receiver.phase == .receiving)
                    // The address copied elsewhere (a message to oneself, the FlareStore link) goes in with one tap and
                    // connects, keyboard or not. The system's own Paste button: no prompt to allow pasting.
                    PasteButton(payloadType: String.self) { [receiver = self.receiver] texts in
                        guard let text = texts.first else { return }
                        Task { @MainActor in receiver.paste(text) }
                    }
                    .labelStyle(.titleAndIcon)
                    .disabled(receiver.phase == .receiving || receiver.phase == .connecting)
                    Button(hostText("Connect")) { receiver.connect() }
                        .disabled(receiver.phase == .receiving || receiver.phase == .connecting || receiver.address.isEmpty)
                } footer: {
                    Text(verbatim: hostText("On the PC, open NX2Apple › Builds › Send to iPhone (Wi-Fi) and type the address it shows. Keep this iPhone on the same Wi-Fi, unlocked, with this screen open."))
                }

                if receiver.phase == .connecting {
                    Section { ProgressView() }
                }

                if !receiver.rows.isEmpty {
                    Section {
                        ForEach(receiver.rows) { row in
                            Button { receiver.toggle(row.id) } label: {
                                HStack(spacing: 12) {
                                    Image(systemName: row.missing.isEmpty ? "checkmark.circle" : (row.selected ? "checkmark.circle.fill" : "circle"))
                                        .foregroundStyle(row.missing.isEmpty ? Color.green : Color.accentColor)
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(verbatim: row.game.name).foregroundStyle(.primary)
                                        Text(verbatim: status(row)).font(.footnote).foregroundStyle(.secondary)
                                    }
                                }
                            }
                            .disabled(row.missing.isEmpty || receiver.phase == .receiving)
                        }
                    } header: {
                        Text(verbatim: hostText("On the PC"))
                    }
                }

                if receiver.phase == .receiving {
                    Section {
                        ProgressView(value: Double(receiver.allDone), total: Double(max(receiver.allTotal, 1)))
                        Text(verbatim: receiver.current).font(.footnote).foregroundStyle(.secondary)
                        Text(verbatim: "\(size(receiver.allDone)) / \(size(receiver.allTotal))").font(.footnote.monospacedDigit())
                        Button(hostText("Stop"), role: .destructive) { receiver.cancel() }
                    }
                } else if !receiver.rows.isEmpty {
                    Section {
                        Button(hostText("Receive (\(size(receiver.selectedBytes)))")) { receiver.receive() }
                            .disabled(receiver.selectedBytes == 0)
                    } footer: {
                        if receiver.rows.allSatisfy(\.missing.isEmpty) {
                            Text(verbatim: hostText("This iPhone already has every game's data the PC offers."))
                        }
                    }
                }

                if receiver.phase == .done {
                    Section { Label(hostText("Received. The games are ready."), systemImage: "checkmark.seal") }
                }
                if case .failed(let message) = receiver.phase {
                    Section { Text(verbatim: message).foregroundStyle(.red) }
                }
            }
            .navigationTitle(Text(verbatim: hostText("Receive from PC")))
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button(hostText("Done")) { receiver.cancel(); onClose() }
                }
            }
        }
    }

    private func status(_ row: PCReceiver.Row) -> String {
        if row.missing.isEmpty { return hostText("On this iPhone") }
        let left = hostText("\(size(row.bytesToFetch)) to receive")
        return row.installed ? left : hostText("Not in this app yet") + " · " + left
    }
}

private extension View {
    /// A field for an address: no capital letters, no corrections, the URL keyboard on the iPhone.
    func addressEntry() -> some View {
        #if os(iOS)
        self.textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
        #else
        self.autocorrectionDisabled()
        #endif
    }
}

#if canImport(UIKit)
/// Presents the screen over whatever is on top (the shell settings are a sheet of their own, which a second SwiftUI sheet
/// from the host view could not present over), as the folder picker does.
@MainActor enum ReceiveFromPCPresenter {
    static func present(_ receiver: PCReceiver, onClose: @escaping @MainActor () -> Void) -> UIViewController? {
        guard let top = DocumentFolderPicker.topViewController() else { return nil }
        var host: UIViewController?
        // Closed, the shell under it takes the hardware keyboard's commands back (ShellFocus.swift).
        let view = ReceiveFromPCView(receiver: receiver) { host?.dismiss(animated: true) { ShellKeyboardFocus.screenClosed() }; onClose() }
        let controller = UIHostingController(rootView: view)
        controller.isModalInPresentation = true   // closed with Done, so a transfer is never dropped by a swipe
        host = controller
        top.present(controller, animated: true)
        return controller
    }
}
#endif
