import Foundation
import MLX
import MLXLLM
import MLXLMCommon
import Tokenizers

/// Cerebro dentro del teléfono: Gemma 4 (E2B o E4B, 4 bits, formato MLX de mlx-community) con mlx-swift-lm.
/// Necesita Metal de verdad: en el simulador de iOS no corre (MLX no lo admite); en el Mac y en el iPhone sí.
actor Cerebro {
    static let shared = Cerebro()

    private var container: ModelContainer?
    private(set) var cargado: String?

    struct Medida: Sendable {
        var primerTrozo: Double = 0       // segundos hasta el primer texto
        var tokens: Int = 0
        var tokensPorSegundo: Double = 0
        var promptTokens: Int = 0
    }

    /// Carga la carpeta del modelo (config.json, model*.safetensors, tokenizer.json…). Devuelve los segundos.
    func cargar(_ carpeta: URL) async throws -> Double {
        if cargado == carpeta.path, container != nil { return 0 }
        descargar()
        // En el teléfono la memoria es justa: poca caché de Metal (los pesos no cuentan aquí).
        GPU.set(cacheLimit: 64 * 1024 * 1024)
        let t = Date()
        container = try await LLMModelFactory.shared.loadContainer(from: carpeta, using: CargadorTokenizer())
        cargado = carpeta.path
        return Date().timeIntervalSince(t)
    }

    func descargar() {
        container = nil
        cargado = nil
        GPU.clearCache()
    }

    /// Respuesta por trozos. `mensajes`: [{role: system|user|assistant, content}].
    func generar(_ mensajes: [[String: String]], temperatura: Float, topP: Float, maxTokens: Int,
                 cancelado: @Sendable () -> Bool = { false },
                 trozo: @Sendable (String) async -> Void) async throws -> Medida {
        guard let container else { throw MotorError("El cerebro del teléfono no está cargado") }
        let chat: [Chat.Message] = mensajes.map { m in
            let c = m["content"] ?? ""
            switch m["role"] {
            case "system": return .system(c)
            case "assistant": return .assistant(c)
            default: return .user(c)
            }
        }
        let t0 = Date()
        let input = try await container.prepare(input: UserInput(chat: chat))
        let params = GenerateParameters(maxTokens: maxTokens, temperature: temperatura, topP: topP)
        var medida = Medida()
        for await g in try await container.generate(input: input, parameters: params) {
            if cancelado() { break }
            switch g {
            case .chunk(let s):
                if medida.primerTrozo == 0 { medida.primerTrozo = Date().timeIntervalSince(t0) }
                await trozo(s)
            case .info(let info):
                medida.tokens = info.generationTokenCount
                medida.tokensPorSegundo = info.tokensPerSecond
                medida.promptTokens = info.promptTokenCount
            default:
                break
            }
        }
        return medida
    }
}

/// Los tokenizadores de swift-transformers adaptados a mlx-swift-lm (lo mismo que su macro
/// #huggingFaceTokenizerLoader, escrito a mano para no depender de macros).
struct CargadorTokenizer: MLXLMCommon.TokenizerLoader {
    func load(from directory: URL) async throws -> any MLXLMCommon.Tokenizer {
        PuenteTokenizer(try await AutoTokenizer.from(modelFolder: directory))
    }
}

struct PuenteTokenizer: MLXLMCommon.Tokenizer {
    let upstream: any Tokenizers.Tokenizer
    init(_ upstream: any Tokenizers.Tokenizer) { self.upstream = upstream }

    func encode(text: String, addSpecialTokens: Bool) -> [Int] { upstream.encode(text: text, addSpecialTokens: addSpecialTokens) }
    func decode(tokenIds: [Int], skipSpecialTokens: Bool) -> String { upstream.decode(tokens: tokenIds, skipSpecialTokens: skipSpecialTokens) }
    func convertTokenToId(_ token: String) -> Int? { upstream.convertTokenToId(token) }
    func convertIdToToken(_ id: Int) -> String? { upstream.convertIdToToken(id) }
    var bosToken: String? { upstream.bosToken }
    var eosToken: String? { upstream.eosToken }
    var unknownToken: String? { upstream.unknownToken }

    func applyChatTemplate(messages: [[String: any Sendable]], tools: [[String: any Sendable]]?,
                           additionalContext: [String: any Sendable]?) throws -> [Int] {
        do {
            return try upstream.applyChatTemplate(messages: messages, tools: tools, additionalContext: additionalContext)
        } catch Tokenizers.TokenizerError.missingChatTemplate {
            throw MLXLMCommon.TokenizerError.missingChatTemplate
        }
    }
}

struct MotorError: Error, CustomStringConvertible {
    let description: String
    init(_ d: String) { description = d }
}
