import Foundation
import Security

/// Claves de API en el llavero del teléfono. Nunca se devuelven a la interfaz ni se imprimen: el puente solo
/// dice si existen, y las peticiones HTTP las ponen en la cabecera aquí, en el lado nativo.
enum Keychain {
    private static let service = "companion.claves"
    static let allowed: Set<String> = ["cloud_key", "groq_key"]

    static func get(_ name: String) -> String? {
        var query = base(name)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &out) == errSecSuccess, let data = out as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func has(_ name: String) -> Bool { !(get(name) ?? "").isEmpty }

    @discardableResult
    static func set(_ name: String, _ value: String) -> Bool {
        remove(name)
        var query = base(name)
        query[kSecValueData as String] = Data(value.utf8)
        query[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        return SecItemAdd(query as CFDictionary, nil) == errSecSuccess
    }

    static func remove(_ name: String) {
        SecItemDelete(base(name) as CFDictionary)
    }

    private static func base(_ name: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: name]
    }
}

#if DEBUG
/// Solo para probar en el simulador: si el lanzamiento trae las claves en el entorno (SIMCTL_CHILD_…), se guardan
/// en el llavero del simulador. No se escriben en ningún archivo ni registro.
enum DebugKeys {
    static func importFromEnvironment() {
        let env = ProcessInfo.processInfo.environment
        for (variable, name) in [("COMPANION_IMPORT_CLOUD_KEY", "cloud_key"), ("COMPANION_IMPORT_GROQ_KEY", "groq_key")] {
            if let value = env[variable]?.trimmingCharacters(in: .whitespacesAndNewlines), !value.isEmpty {
                Keychain.set(name, value)
            }
        }
    }
}
#endif
