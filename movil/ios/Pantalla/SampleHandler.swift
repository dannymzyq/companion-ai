import CoreImage
import CryptoKit
import Foundation
import Network
import ReplayKit
import Security

/// Compartir pantalla (extensión de transmisión de iOS): iOS le pasa lo que se ve en la pantalla del iPhone, en
/// cualquier app. Una imagen cada ~0,8 s, reducida, en JPEG y autenticada con ChaChaPoly-256, va a Companion por
/// un puerto efímero local (127.0.0.1) leído del App Group Keychain. Nada sale del teléfono desde aquí.
final class SampleHandler: RPBroadcastSampleHandler {
    private static let sharedService = "companion.claves"
    private static let sharedGroup = "group.local.companion.app"
    private static let ipcSlot = "pantalla_ipc"

    private var conexion: NWConnection?
    private var clave: SymmetricKey?
    private let cola = DispatchQueue(label: "pantalla")
    private let ci = CIContext(options: [.cacheIntermediates: false])
    private var ultima = Date.distantPast
    private var enviando = false

    override func broadcastStarted(withSetupInfo setupInfo: [String: NSObject]?) {
        conectar()
    }

    private static func leerCredencialIpc() -> (NWEndpoint.Port, SymmetricKey)? {
        func buscar(conGrupo: Bool) -> String? {
            var q: [String: Any] = [
                kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: sharedService,
                kSecAttrAccount as String: conGrupo ? ipcSlot : "shared_\(ipcSlot)",
                kSecReturnData as String: true,
                kSecMatchLimit as String: kSecMatchLimitOne,
            ]
            if conGrupo { q[kSecAttrAccessGroup as String] = sharedGroup }
            var out: CFTypeRef?
            guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let data = out as? Data else { return nil }
            return String(data: data, encoding: .utf8)
        }
        guard let raw = buscar(conGrupo: true) ?? buscar(conGrupo: false),
              let sep = raw.firstIndex(of: ":"),
              let portNum = UInt16(raw[..<sep]),
              let port = NWEndpoint.Port(rawValue: portNum),
              let keyData = Data(base64Encoded: String(raw[raw.index(after: sep)...])),
              keyData.count == 32 else { return nil }
        return (port, SymmetricKey(data: keyData))
    }

    private func conectar() {
        guard let (puerto, sym) = Self.leerCredencialIpc() else { return }
        clave = sym
        let c = NWConnection(host: "127.0.0.1", port: puerto, using: .tcp)
        c.stateUpdateHandler = { [weak self] estado in
            guard let self else { return }
            switch estado {
            case .ready: self.escuchar(c)
            case .failed, .cancelled:
                if self.conexion === c { self.conexion = nil }
            default: break
            }
        }
        conexion = c
        c.start(queue: cola)
    }

    /// La app manda un byte 0x53 («S») cuando el usuario pulsa «dejar de compartir» en Companion.
    private func escuchar(_ c: NWConnection) {
        c.receive(minimumIncompleteLength: 1, maximumLength: 16) { [weak self] data, _, fin, error in
            if let data, data.contains(0x53) {
                self?.finishBroadcastWithError(NSError(domain: "Companion", code: 0,
                    userInfo: [NSLocalizedDescriptionKey: "Dejaste de compartir la pantalla en Companion."]))
                return
            }
            if !fin && error == nil { self?.escuchar(c) }
        }
    }

    override func processSampleBuffer(_ sampleBuffer: CMSampleBuffer, with sampleBufferType: RPSampleBufferType) {
        guard sampleBufferType == .video, !enviando, Date().timeIntervalSince(ultima) > 0.8,
              let px = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        ultima = Date()
        if conexion == nil { cola.async { self.conectar() }; return }
        var img = CIImage(cvPixelBuffer: px)
        if let o = CMGetAttachment(sampleBuffer, key: RPVideoSampleOrientationKey as CFString, attachmentModeOut: nil) as? NSNumber,
           let ori = CGImagePropertyOrientation(rawValue: o.uint32Value) { img = img.oriented(ori) }
        let lado = max(img.extent.width, img.extent.height)
        let escala = min(1, 1280 / lado)
        img = img.transformed(by: CGAffineTransform(scaleX: escala, y: escala))
        guard let jpeg = ci.jpegRepresentation(of: img, colorSpace: CGColorSpaceCreateDeviceRGB(),
                                               options: [kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption: 0.6]),
              let sym = clave,
              let box = try? ChaChaPoly.seal(jpeg, using: sym),
              let c = conexion else { return }
        let cifrado = box.combined
        var largo = UInt32(cifrado.count).bigEndian
        var paquete = Data(bytes: &largo, count: 4)
        paquete.append(cifrado)
        enviando = true
        c.send(content: paquete, completion: .contentProcessed { [weak self] _ in self?.enviando = false })
    }

    override func broadcastFinished() {
        conexion?.cancel()
        conexion = nil
    }
}
