package local.companion.app

import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString

/**
 * El WebSocket del modo «En vivo» (Gemini Live), abierto en nativo para que la clave no pase por la página: el
 * nativo la pone en la dirección y solo conecta con la Live API de Google (como LiveSocket.swift).
 */
class LiveSocket(private val id: Int, private val bridge: Bridge) {
    companion object { val HOSTS = setOf("generativelanguage.googleapis.com") }
    private var ws: WebSocket? = null

    fun open(url: String, keyName: String?) {
        val u = url.replaceFirst("wss://", "https://").toHttpUrlOrNull()
        if (!url.startsWith("wss://") || u == null || u.host !in HOSTS) throw BridgeError("En vivo solo se conecta a la Live API de Google")
        val b = u.newBuilder()
        if (keyName != null) {
            val key = Secretos.get(bridge.ctx, bridge.secreto(keyName)) ?: throw BridgeError("Falta la clave")
            b.removeAllQueryParameters("key").addQueryParameter("key", key)
        }
        ws = bridge.http.newWebSocket(Request.Builder().url(b.build()).build(), object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {}
            override fun onMessage(webSocket: WebSocket, text: String) = bridge.evento(id, "message", text)
            override fun onMessage(webSocket: WebSocket, bytes: ByteString) = bridge.evento(id, "message", bytes.utf8())
            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(1000, null)
                if (ws !== webSocket) return
                ws = null
                if (code == 1000) bridge.evento(id, "end", null)
                else bridge.evento(id, "error", "En vivo se cortó: ${reason.ifEmpty { "código $code" }}")
            }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                if (ws !== webSocket) return
                ws = null
                bridge.evento(id, "error", "En vivo se cortó: sin conexión (${t.javaClass.simpleName})")
            }
        })
        bridge.evento(id, "open", null)
    }

    fun send(text: String) {
        if (ws?.send(text) != true) throw BridgeError("En vivo no está conectado")
    }

    fun close() { ws?.close(1000, null); ws = null }
}
