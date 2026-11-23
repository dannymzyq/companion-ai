package local.companion.app

import android.Manifest
import android.app.PictureInPictureParams
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Base64
import android.util.Log
import android.webkit.WebView
import androidx.core.content.ContextCompat
import androidx.webkit.JavaScriptReplyProxy
import androidx.webkit.WebMessageCompat
import androidx.webkit.WebViewCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.TimeUnit

/**
 * Puente JS ↔ nativo (movil/core/platform.js). Mismos comandos que Bridge.swift en iOS: cada mensaje es
 * {id, cmd, args} y la respuesta {id, value} o {id, error}. Los flujos mandan window.__native.event(id, kind, data)
 * y los avisos sin petición window.__native.emit(kind, data).
 */
class Bridge(private val act: MainActivity) : WebViewCompat.WebMessageListener {
    companion object {
        const val TAG = "Companion"

        /** platform.js busca window.companionNative.post(msg) → Promise. Aquí se monta sobre el canal de mensajes. */
        val SHIM = """
            (() => {
              if (window.companionNative || !window.companionPuente) return;
              const pend = new Map(); let n = 0;
              window.companionPuente.onmessage = (e) => {
                let r; try { r = JSON.parse(e.data); } catch { return; }
                const p = pend.get(r.id); if (!p) return; pend.delete(r.id);
                p({ value: r.value === undefined ? null : r.value, error: r.error });
              };
              window.companionNative = {
                platform: 'android',
                post(msg) { return new Promise((res) => { const id = ++n; pend.set(id, res);
                  window.companionPuente.postMessage(JSON.stringify({ id, cmd: msg.cmd, args: msg.args || {} })); }); },
              };
            })();
        """.trimIndent()

        fun carpetaVrm(ctx: Context) = File(ctx.filesDir, "companion/vrm").apply { mkdirs() }
        private val KV_RE = Regex("^[a-z0-9_-]{1,40}$")
        private val ID_RE = Regex("^[a-z0-9_-]{1,60}$")
    }

    val ctx: Context get() = act
    private val main = Handler(Looper.getMainLooper())
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS).readTimeout(0, TimeUnit.SECONDS).pingInterval(20, TimeUnit.SECONDS).build()
    private val kvDir = File(act.filesDir, "companion/kv").apply { mkdirs() }
    private val streams = mutableMapOf<Int, Job>()
    private val calls = mutableMapOf<Int, okhttp3.Call>()
    private val sockets = mutableMapOf<Int, LiveSocket>()
    val pantalla = Pantalla(act, this)

    override fun onPostMessage(view: WebView, message: WebMessageCompat, sourceOrigin: Uri, isMainFrame: Boolean,
                               reply: JavaScriptReplyProxy) {
        if (!isMainFrame || sourceOrigin.toString().trimEnd('/') != MainActivity.ORIGEN) return
        val msg = try { JSONObject(message.data ?: return) } catch (e: Exception) { return }
        val id = msg.optInt("id")
        val cmd = msg.optString("cmd")
        val args = msg.optJSONObject("args") ?: JSONObject()
        scope.launch {
            val out = JSONObject().put("id", id)
            try {
                out.put("value", handle(cmd, args) ?: JSONObject.NULL)
            } catch (e: Exception) {
                out.put("error", (e as? BridgeError)?.message ?: e.message ?: e.javaClass.simpleName)
            }
            reply.postMessage(out.toString())
        }
    }

    private suspend fun handle(cmd: String, a: JSONObject): Any? = when (cmd) {
        "app.info" -> JSONObject()
            .put("platform", "android").put("simulator", Build.FINGERPRINT.contains("generic") || Build.MODEL.contains("sdk"))
            .put("version", BuildConfig.VERSION_NAME)
            .put("can", JSONObject()
                // El modo «todo dentro del teléfono» (MLX, WhisperKit) aún no existe en Android.
                .put("LIGHT_VOICE", false).put("LOCAL_EAR", false).put("LOCAL_BRAIN", false).put("SILERO", false)
                .put("simulator", false).put("memory_total", Runtime.getRuntime().maxMemory()))
        "mic.permission" -> when {
            act.tiene(Manifest.permission.RECORD_AUDIO) -> "granted"
            else -> "undetermined"
        }
        "log" -> { Log.i(TAG, "[web ${a.optString("level")}] ${a.optString("text")}"); true }
        "kv.get" -> kvFile(a.optString("key")).let { if (it.isFile) it.readText() else null }
        "kv.set" -> withContext(Dispatchers.IO) {
            val f = kvFile(a.optString("key"))
            val tmp = File(f.path + ".tmp")
            tmp.writeText(if (a.isNull("value")) "null" else a.optString("value", "null"))
            tmp.renameTo(f); true
        }
        "secret.has" -> Secretos.has(act, secreto(a.optString("name")))
        "secret.set" -> {
            val v = a.optString("value").trim()
            if (v.isEmpty()) throw BridgeError("Clave vacía")
            Secretos.set(act, secreto(a.optString("name")), v)
        }
        "secret.remove" -> { Secretos.remove(act, secreto(a.optString("name"))); true }
        "http.request" -> withContext(Dispatchers.IO) {
            http.newBuilder().callTimeout(a.optDouble("timeout", 30.0).toLong(), TimeUnit.SECONDS).build()
                .newCall(request(a)).execute().use { r ->
                    JSONObject().put("status", r.code).put("body", r.body?.string() ?: "")
                }
        }
        "http.stream" -> {
            val id = a.optInt("stream", -1).takeIf { it >= 0 } ?: throw BridgeError("Falta el id del flujo")
            val req = request(a)
            streams[id] = scope.launch(Dispatchers.IO) { runStream(id, req) }
            true
        }
        "ws.collect" -> withContext(Dispatchers.IO) {
            val url = a.optString("url")
            if (!url.startsWith("wss://")) throw BridgeError("Solo se permiten direcciones wss://")
            val headers = a.optJSONObject("headers")?.let { h -> h.keys().asSequence().associateWith { h.getString(it) } } ?: emptyMap()
            val msgs = a.optJSONArray("messages")?.let { m -> (0 until m.length()).map { m.getString(it) } } ?: emptyList()
            when (val r = SocketCollect.run(http, url, headers, msgs, a.optString("endPath", "turn.end"), a.optDouble("timeout", 20.0))) {
                is SocketCollect.Result.Ok -> JSONObject().put("audio", Base64.encodeToString(r.audio, Base64.NO_WRAP))
                is SocketCollect.Result.Fail -> JSONObject().put("error", r.message).put("date", r.date ?: JSONObject.NULL)
            }
        }
        "live.open" -> {
            val id = a.optInt("stream", -1).takeIf { it >= 0 } ?: throw BridgeError("Falta el id")
            sockets.remove(id)?.close()
            val s = LiveSocket(id, this)
            s.open(a.optString("url"), a.optString("auth").ifEmpty { null })
            sockets[id] = s
            true
        }
        "live.send" -> {
            val s = sockets[a.optInt("id")] ?: throw BridgeError("En vivo no está conectado")
            s.send(a.optString("text")); true
        }
        "vrm.write" -> withContext(Dispatchers.IO) {
            val f = propio(a.optString("id"))
            val chunk = Base64.decode(a.optString("data"), Base64.DEFAULT)
            FileOutputStream(f, !a.optBoolean("first")).use { it.write(chunk) }
            true
        }
        "vrm.remove" -> { propio(a.optString("id")).delete(); true }
        // Ventana flotante: en Android es la propia app en pequeño (MainActivity); no hacen falta cuadros.
        "pip.open" -> {
            if (!act.packageManager.hasSystemFeature(PackageManager.FEATURE_PICTURE_IN_PICTURE)) throw BridgeError("Este teléfono no admite ventanas flotantes")
            act.flotanteArmada = true; JSONObject().put("native", true)
        }
        "pip.frame" -> act.isInPictureInPictureMode
        "pip.close" -> { act.flotanteArmada = false; true }
        "screen.start" -> pantalla.empezar()
        "screen.stop" -> { pantalla.parar(); true }
        "audio.mode" -> true
        "stream.cancel" -> {
            val id = a.optInt("id")
            sockets.remove(id)?.close()
            calls.remove(id)?.cancel()
            streams.remove(id)?.cancel()
            true
        }
        else -> throw BridgeError("En Android aún no existe: $cmd")
    }

    private fun runStream(id: Int, req: Request) {
        val t0 = System.currentTimeMillis()
        val call = http.newCall(req)
        calls[id] = call
        try {
            call.execute().use { r ->
                Log.i(TAG, "flujo $id ${req.url.host}: ${r.code} a los ${(System.currentTimeMillis() - t0) / 1000.0} s")
                evento(id, "head", JSONObject().put("status", r.code).put("id", id))
                val src = r.body?.source() ?: return@use
                while (true) {
                    val line = src.readUtf8Line() ?: break
                    evento(id, "line", line)
                }
                evento(id, "end", null)
            }
        } catch (e: Exception) {
            if (call.isCanceled()) evento(id, "end", null)
            else evento(id, "error", "Sin conexión (${e.javaClass.simpleName})")
        } finally {
            calls.remove(id); streams.remove(id)
        }
    }

    private fun request(a: JSONObject): Request {
        val url = a.optString("url")
        if (!url.startsWith("https://")) throw BridgeError("Solo se permiten direcciones https://")
        val b = Request.Builder().url(url)
        a.optJSONObject("headers")?.let { h ->
            for (k in h.keys()) if (!k.equals("authorization", true)) b.header(k, h.getString(k))
        }
        val method = a.optString("method", "GET").uppercase()
        var body: RequestBody? = null
        if (!a.isNull("body") && a.has("body")) {
            val ct = a.optJSONObject("headers")?.let { h -> h.keys().asSequence().firstOrNull { it.equals("content-type", true) }?.let { h.getString(it) } }
            body = a.getString("body").toRequestBody(ct?.toMediaTypeOrNull())
        }
        a.optJSONObject("multipart")?.let { mp ->
            val m = MultipartBody.Builder().setType(MultipartBody.FORM)
            mp.optJSONObject("fields")?.let { f -> for (k in f.keys()) m.addFormDataPart(k, f.getString(k)) }
            mp.optJSONObject("file")?.let { f ->
                val bytes = Base64.decode(f.optString("base64"), Base64.DEFAULT)
                m.addFormDataPart(f.optString("field", "file"), f.optString("name", "audio.wav"),
                    bytes.toRequestBody(f.optString("mime", "application/octet-stream").toMediaTypeOrNull()))
            }
            body = m.build()
        }
        if (body == null && method in setOf("POST", "PUT", "PATCH")) body = ByteArray(0).toRequestBody(null)
        b.method(method, body)
        val bearer = a.optString("bearer")
        if (bearer.isNotEmpty()) b.header("Authorization", "Bearer $bearer")
        else if (a.has("auth") && !a.isNull("auth")) {
            val key = Secretos.get(act, secreto(a.getString("auth"))) ?: throw BridgeError("Falta la clave")
            b.header("Authorization", "Bearer $key")
        }
        return b.build()
    }

    private fun kvFile(key: String): File {
        if (!KV_RE.matches(key)) throw BridgeError("Nombre no válido")
        return File(kvDir, "$key.json")
    }
    private fun propio(id: String): File {
        if (!ID_RE.matches(id)) throw BridgeError("Identificador no válido")
        return File(carpetaVrm(act), "$id.vrm")
    }
    fun secreto(name: String): String {
        if (name !in Secretos.PERMITIDOS) throw BridgeError("Secreto no permitido")
        return name
    }

    // ---------------------------------------------------------------- hacia la página
    fun evento(id: Int, kind: String, data: Any?) {
        val json = JSONArray().put(data ?: JSONObject.NULL).toString()
        main.post { act.web.evaluateJavascript("window.__native.event($id, \"$kind\", $json[0])", null) }
    }

    fun emitir(kind: String, dataJs: String) {
        main.post { act.web.evaluateJavascript("window.__native && window.__native.emit('$kind', $dataJs)", null) }
    }

    fun pantallaPermitida(code: Int, data: Intent?) = pantalla.permitida(code, data)

    fun cerrarTodo() {
        sockets.values.forEach { it.close() }; sockets.clear()
        calls.values.forEach { it.cancel() }
        pantalla.parar()
        scope.cancel()
    }
}

class BridgeError(message: String) : Exception(message)
