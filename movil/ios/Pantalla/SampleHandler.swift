import CoreImage
import Network
import ReplayKit

/// Compartir pantalla (extensión de transmisión de iOS): iOS le pasa lo que se ve en la pantalla del iPhone, en
/// cualquier app. Una imagen cada ~0,8 s, reducida y en JPEG, va a la app de Companion por una conexión local
/// (127.0.0.1, ReceptorPantalla.swift), que la pasa a la página como la pantalla compartida de la PC. Nada sale del
/// teléfono desde aquí. Las extensiones tienen ~50 MB de memoria: nada se guarda, cada imagen se manda y se suelta.
final class SampleHandler: RPBroadcastSampleHandler {
    static let puerto: NWEndpoint.Port = 47_621
    private var conexion: NWConnection?
    private let cola = DispatchQueue(label: "pantalla")
    private let ci = CIContext(options: [.cacheIntermediates: false])
    private var ultima = Date.distantPast
    private var enviando = false

    override func broadcastStarted(withSetupInfo setupInfo: [String: NSObject]?) {
        conectar()
    }

    private func conectar() {
        let c = NWConnection(host: "127.0.0.1", port: Self.puerto, using: .tcp)
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
        // Girada si iOS la entrega de lado (la orientación va como adjunto del cuadro).
        if let o = CMGetAttachment(sampleBuffer, key: RPVideoSampleOrientationKey as CFString, attachmentModeOut: nil) as? NSNumber,
           let ori = CGImagePropertyOrientation(rawValue: o.uint32Value) { img = img.oriented(ori) }
        let lado = max(img.extent.width, img.extent.height)
        let escala = min(1, 1280 / lado)
        img = img.transformed(by: CGAffineTransform(scaleX: escala, y: escala))
        guard let jpeg = ci.jpegRepresentation(of: img, colorSpace: CGColorSpaceCreateDeviceRGB(),
                                               options: [kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption: 0.6]),
              let c = conexion else { return }
        var largo = UInt32(jpeg.count).bigEndian
        var paquete = Data(bytes: &largo, count: 4)
        paquete.append(jpeg)
        enviando = true
        c.send(content: paquete, completion: .contentProcessed { [weak self] _ in self?.enviando = false })
    }

    override func broadcastFinished() {
        conexion?.cancel()
        conexion = nil
    }
}
