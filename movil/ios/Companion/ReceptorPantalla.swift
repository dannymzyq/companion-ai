import CryptoKit
import Network
import ReplayKit
import UIKit

/// Recibe la pantalla compartida de la extensión de transmisión (Pantalla/SampleHandler.swift) por una conexión
/// local autenticada y cifrada con ChaChaPoly en un puerto efímero sobre 127.0.0.1 (compartido por App Group Keychain).
@MainActor
final class ReceptorPantalla {
    static let ipcSlot = "pantalla_ipc"
    private var listener: NWListener?
    private var conexion: NWConnection?
    private var clave: SymmetricKey?
    private var buffer = Data()
    var alCuadro: ((Data) -> Void)?
    var alCambiar: ((Bool) -> Void)?
    private(set) var activa = false
    private var cuenta = 0

    func escuchar() throws {
        guard listener == nil else { return }
        let sym = SymmetricKey(size: .bits256)
        clave = sym
        let keyB64 = sym.withUnsafeBytes { Data($0).base64EncodedString() }
        let p = NWParameters.tcp
        p.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: .any)
        let l = try NWListener(using: p)
        l.stateUpdateHandler = { estado in
            switch estado {
            case .ready:
                if let port = l.port?.rawValue {
                    Keychain.sharedSet(Self.ipcSlot, "\(port):\(keyB64)")
                }
            case .failed(let e):
                #if PRUEBAS
                Task { @MainActor in Registro.anotar("Pantalla compartida: no pude escuchar: \(e)") }
                #else
                _ = e
                #endif
            default:
                break
            }
        }
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
                case .ready:
                    self.activa = true; self.alCambiar?(true); self.leer(c)
                    #if PRUEBAS
                    Registro.anotar("Pantalla compartida: conectada")
                    #endif
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
        guard let clave else { buffer.removeAll(); return }
        while buffer.count >= 4 {
            let largo = buffer.prefix(4).reduce(0) { ($0 << 8) | Int($1) }
            guard largo > 28, largo < 8 << 20 else { buffer.removeAll(); return }
            guard buffer.count >= 4 + largo else { return }
            let cifrado = buffer.subdata(in: buffer.startIndex + 4 ..< buffer.startIndex + 4 + largo)
            buffer.removeSubrange(buffer.startIndex ..< buffer.startIndex + 4 + largo)
            guard let box = try? ChaChaPoly.SealedBox(combined: cifrado),
                  let jpeg = try? ChaChaPoly.open(box, using: clave) else {
                conexion?.cancel()
                buffer.removeAll()
                return
            }
            alCuadro?(jpeg)
            #if PRUEBAS
            cuenta += 1
            if cuenta % 15 == 1 { Registro.anotar("Pantalla compartida: \(cuenta) imágenes (\(jpeg.count / 1024) KB la última)") }
            #endif
        }
    }

    private func terminar(_ c: NWConnection) {
        guard conexion === c else { return }
        conexion = nil
        buffer.removeAll()
        if activa { activa = false; alCambiar?(false) }
        #if PRUEBAS
        Registro.anotar("Pantalla compartida: terminada tras \(cuenta) imágenes")
        #endif
        cuenta = 0
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
