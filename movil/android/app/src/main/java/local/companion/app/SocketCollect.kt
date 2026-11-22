package local.companion.app

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import java.io.ByteArrayOutputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Voz en la nube (Edge): manda los mensajes, junta el audio binario hasta «Path:<endPath>» (como SocketCollect.swift). */
object SocketCollect {
    sealed class Result { class Ok(val audio: ByteArray) : Result(); class Fail(val message: String, val date: String?) : Result() }

    fun run(http: OkHttpClient, url: String, headers: Map<String, String>, messages: List<String>, endPath: String, timeout: Double): Result {
        val audio = ByteArrayOutputStream()
        val done = CountDownLatch(1)
        var fail: Result.Fail? = null
        val b = Request.Builder().url(url)
        headers.forEach { (k, v) -> b.header(k, v) }
        val ws = http.newWebSocket(b.build(), object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) { messages.forEach { webSocket.send(it) } }
            override fun onMessage(webSocket: WebSocket, text: String) { if (text.contains("Path:$endPath")) done.countDown() }
            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                if (bytes.size < 2) return
                val start = 2 + ((bytes[0].toInt() and 0xff) shl 8 or (bytes[1].toInt() and 0xff))
                if (start < bytes.size) synchronized(audio) { audio.write(bytes.toByteArray(), start, bytes.size - start) }
            }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                fail = Result.Fail("La voz en la nube no respondió (${response?.code ?: t.javaClass.simpleName})", response?.header("Date"))
                done.countDown()
            }
        })
        val ok = done.await((timeout * 1000).toLong(), TimeUnit.MILLISECONDS)
        ws.close(1000, null)
        fail?.let { return it }
        if (!ok) return Result.Fail("La voz en la nube tardó demasiado", null)
        return Result.Ok(synchronized(audio) { audio.toByteArray() })
    }
}
