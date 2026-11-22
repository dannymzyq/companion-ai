package local.companion.app

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Las claves (Gemini, Groq, En vivo), cifradas con una clave del almacén de Android (Keystore, no sale del
 * teléfono). Como el llavero en iOS: la página nunca las lee; el nativo las pone en las peticiones.
 */
object Secretos {
    val PERMITIDOS = setOf("cloud_key", "groq_key", "live_key")
    private const val ALIAS = "companion.claves"
    private const val PREFS = "claves"

    private fun clave(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val g = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        g.init(KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256).build())
        return g.generateKey()
    }

    fun set(ctx: Context, name: String, value: String): Boolean {
        val c = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, clave()) }
        val out = c.iv + c.doFinal(value.toByteArray())
        return ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString(name, Base64.encodeToString(out, Base64.NO_WRAP)).commit()
    }

    fun get(ctx: Context, name: String): String? {
        val s = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(name, null) ?: return null
        return try {
            val raw = Base64.decode(s, Base64.NO_WRAP)
            val c = Cipher.getInstance("AES/GCM/NoPadding")
            c.init(Cipher.DECRYPT_MODE, clave(), GCMParameterSpec(128, raw, 0, 12))
            String(c.doFinal(raw, 12, raw.size - 12))
        } catch (e: Exception) { null }
    }

    fun has(ctx: Context, name: String) = !get(ctx, name).isNullOrEmpty()
    fun remove(ctx: Context, name: String) { ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().remove(name).commit() }
}
