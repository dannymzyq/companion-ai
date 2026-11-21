import Network
import ReplayKit
import UIKit

/// Recibe la pantalla compartida de la extensión de transmisión (Pantalla/SampleHandler.swift) por una conexión
/// local (solo 127.0.0.1: el puerto no se abre a la red) y pasa cada imagen a la página (`pantalla`).
@MainActor
final class ReceptorPantalla {
    static let puerto: NWEndpoint.Port = 47_621
    private var listener: NWListener?
    private var conexion: NWConnection?
    private var buffer = Data()
    var alCuadro: ((Data) -> Void)?
    var alCambiar: ((Bool) -> Void)?
    private(set) var activa = false

    func escuchar() throws {
        guard listener == nil else { return }
        let p = NWParameters.tcp
        p.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: Self.puerto)
        p.allowLocalEndpointReuse = true
        let l = try NWListener(using: p)
        l.newConnectionHandler = { [weak self] c in
            Task { @MainActor in self?.aceptar(c) }
        }
        l.start(queue: .main)
        listener = l
    }

    private func aceptar(_ c: NWConnection) {
        conexion?.cancel()
        conexion = c
        buffer.removeAll()
        c.stateUpdateHandler = { [weak self] estado in
            Task { @MainActor in
                guard let self, self.conexion === c else { return }
                switch estado {
                case .ready: self.activa = true; self.alCambiar?(true); self.leer(c)
                case .failed, .cancelled: self.terminar(c)
                default: break
                }
            }
        }
        c.start(queue: .main)
    }

    private func leer(_ c: NWConnection) {
        c.receive(minimumIncompleteLength: 1, maximumLength: 1 << 20) { [weak self] data, _, fin, error in
            Task { @MainActor in
                guard let self, self.conexion === c else { return }
                if let data { self.buffer.append(data); self.sacarCuadros() }
                if fin || error != nil { self.terminar(c) } else { self.leer(c) }
            }
        }
    }

    private func sacarCuadros() {
        while buffer.count >= 4 {
            let largo = buffer.prefix(4).reduce(0) { ($0 << 8) | Int($1) }
            guard largo > 0, largo < 8 << 20 else { buffer.removeAll(); return }
            guard buffer.count >= 4 + largo else { return }
            let jpeg = buffer.subdata(in: buffer.startIndex + 4 ..< buffer.startIndex + 4 + largo)
            buffer.removeSubrange(buffer.startIndex ..< buffer.startIndex + 4 + largo)
            alCuadro?(jpeg)
        }
    }

    private func terminar(_ c: NWConnection) {
        guard conexion === c else { return }
        conexion = nil
        buffer.removeAll()
        if activa { activa = false; alCambiar?(false) }
    }

    /// «Dejar de compartir» desde Companion: la extensión termina la transmisión.
    func parar() {
        conexion?.send(content: Data([0x53]), completion: .contentProcessed { _ in })
    }

    /// Abre la hoja de iOS para empezar a transmitir la pantalla (con Companion ya elegida).
    static func pedirTransmision(en vista: UIView) {
        let picker = RPSystemBroadcastPickerView(frame: CGRect(x: -100, y: -100, width: 44, height: 44))
        picker.preferredExtension = (Bundle.main.bundleIdentifier ?? "local.companion.app") + ".pantalla"
        picker.showsMicrophoneButton = false
        vista.addSubview(picker)
        for case let b as UIButton in picker.subviews { b.sendActions(for: .touchUpInside) }
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { picker.removeFromSuperview() }
    }
}
