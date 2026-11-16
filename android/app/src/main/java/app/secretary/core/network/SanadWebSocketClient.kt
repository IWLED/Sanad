package app.secretary.core.network

import android.os.Handler
import android.os.Looper
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID
import java.util.concurrent.TimeUnit

enum class ConnectionStatus {
    DISCONNECTED,
    CONNECTING,
    CONNECTED
}

data class ActionRecipient(
    val name: String,
    val phone: String? = null
)

data class ThreadMessage(
    val who: String,
    val text: String,
    val ts: String
)

data class ActionPreview(
    val title: String,
    val app: String,
    val recipient: ActionRecipient?,
    val threadContext: List<ThreadMessage>,
    val draftText: String,
    val warnings: List<String>
)

sealed interface ServerWsEvent {
    data class Welcome(val missedCount: Int) : ServerWsEvent
    data class Pong(val serverTime: String) : ServerWsEvent
    data class AssistantMessage(val text: String, val ttsOk: Boolean) : ServerWsEvent
    data class ActionRequest(
        val actionId: String,
        val version: Int,
        val kind: String,
        val executor: String,
        val riskTier: Int,
        val argsHash: String,
        val expiresAt: String,
        val requiresBiometric: Boolean,
        val preview: ActionPreview
    ) : ServerWsEvent
    data class ActionUpdate(
        val actionId: String,
        val version: Int,
        val status: String,
        val detail: String?
    ) : ServerWsEvent
    data class ExecCommand(
        val actionId: String,
        val version: Int,
        val kind: String,
        val args: JSONObject
    ) : ServerWsEvent
    data class Error(val code: String, val message: String) : ServerWsEvent
}

class SanadWebSocketClient(
    private val serverUrl: String,
    private val token: String,
    private val okHttpClient: OkHttpClient = OkHttpClient.Builder()
        .pingInterval(25, TimeUnit.SECONDS)
        .build()
) {
    companion object {
        private const val TAG = "SanadWebSocket"
    }

    private var webSocket: WebSocket? = null
    private var pingJob: Job? = null
    private var lastSeq: Long = 0
    private val coroutineScope = CoroutineScope(Dispatchers.IO)

    private val _connectionStatus = MutableStateFlow(ConnectionStatus.DISCONNECTED)
    val connectionStatus: StateFlow<ConnectionStatus> = _connectionStatus.asStateFlow()

    private val _events = MutableSharedFlow<ServerWsEvent>(extraBufferCapacity = 64)
    val events: SharedFlow<ServerWsEvent> = _events.asSharedFlow()

    fun connect() {
        if (_connectionStatus.value == ConnectionStatus.CONNECTED) return
        _connectionStatus.value = ConnectionStatus.CONNECTING

        val wsUrl = if (serverUrl.startsWith("https://")) {
            serverUrl.replace("https://", "wss://")
        } else if (serverUrl.startsWith("http://")) {
            serverUrl.replace("http://", "ws://")
        } else {
            "ws://$serverUrl"
        } + "/v1/ws?token=$token"

        val request = Request.Builder().url(wsUrl).build()
        webSocket = okHttpClient.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.i(TAG, "WebSocket connected successfully")
                _connectionStatus.value = ConnectionStatus.CONNECTED
                sendHello()
                startPingTimer()
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                try {
                    handleIncomingMessage(JSONObject(text))
                } catch (e: Exception) {
                    Log.e(TAG, "Error parsing message: $text", e)
                }
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                Log.w(TAG, "WebSocket closing code=$code reason=$reason")
                _connectionStatus.value = ConnectionStatus.DISCONNECTED
                stopPingTimer()
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.i(TAG, "WebSocket closed")
                _connectionStatus.value = ConnectionStatus.DISCONNECTED
                stopPingTimer()
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e(TAG, "WebSocket connection failed: ${t.message}", t)
                _connectionStatus.value = ConnectionStatus.DISCONNECTED
                stopPingTimer()
            }
        })
    }

    fun disconnect() {
        stopPingTimer()
        webSocket?.close(1000, "User disconnected")
        webSocket = null
        _connectionStatus.value = ConnectionStatus.DISCONNECTED
    }

    private fun startPingTimer() {
        pingJob?.cancel()
        pingJob = coroutineScope.launch {
            while (isActive) {
                delay(25_000)
                sendEnvelope("ping", JSONObject())
            }
        }
    }

    private fun stopPingTimer() {
        pingJob?.cancel()
        pingJob = null
    }

    private fun sendHello() {
        val payload = JSONObject().apply {
            put("last_seq", lastSeq)
            put("app_version", "1.0.0")
            put("capabilities", JSONArray().apply {
                put("hitl_v1")
                put("chat_v1")
            })
        }
        sendEnvelope("hello", payload)
    }

    fun sendUserMessage(text: String, clientMsgId: String = UUID.randomUUID().toString()) {
        val payload = JSONObject().apply {
            put("client_msg_id", clientMsgId)
            put("text", text)
        }
        sendEnvelope("user_message", payload)
    }

    fun sendActionDecision(
        actionId: String,
        version: Int,
        argsHash: String,
        decision: String,
        editedText: String? = null,
        biometricOk: Boolean = false
    ) {
        val payload = JSONObject().apply {
            put("action_id", actionId)
            put("version", version)
            put("args_hash", argsHash)
            put("decision", decision)
            if (editedText != null) {
                put("edited_text", editedText)
            }
            put("biometric_ok", biometricOk)
        }
        sendEnvelope("action_decision", payload)
    }

    fun sendDeviceExecResult(
        actionId: String,
        version: Int,
        status: String,
        detail: String? = null,
        fallbackUsed: Boolean = false
    ) {
        val payload = JSONObject().apply {
            put("action_id", actionId)
            put("version", version)
            put("status", status)
            if (detail != null) {
                put("detail", detail)
            }
            put("fallback_used", fallbackUsed)
        }
        sendEnvelope("device_exec_result", payload)
    }

    private fun sendAck(seq: Long) {
        val payload = JSONObject().apply {
            put("seq", seq)
        }
        sendEnvelope("ack", payload)
    }

    private fun sendEnvelope(type: String, payload: JSONObject) {
        val envelope = JSONObject().apply {
            put("v", 1)
            put("type", type)
            put("id", UUID.randomUUID().toString())
            put("ts", SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US).format(Date()))
            put("payload", payload)
        }
        webSocket?.send(envelope.toString())
    }

    private fun handleIncomingMessage(json: JSONObject) {
        val type = json.optString("type")
        val seq = if (json.has("seq") && !json.isNull("seq")) json.getLong("seq") else null
        val payload = json.optJSONObject("payload") ?: JSONObject()

        if (seq != null) {
            if (seq > lastSeq) {
                lastSeq = seq
            }
            sendAck(seq)
        }

        coroutineScope.launch {
            when (type) {
                "welcome" -> {
                    val missed = payload.optInt("missed_count", 0)
                    _events.emit(ServerWsEvent.Welcome(missed))
                }
                "pong" -> {
                    val serverTime = payload.optString("server_time")
                    _events.emit(ServerWsEvent.Pong(serverTime))
                }
                "assistant_message" -> {
                    val text = payload.optString("text")
                    val ttsOk = payload.optBoolean("tts_ok", true)
                    _events.emit(ServerWsEvent.AssistantMessage(text, ttsOk))
                }
                "action_request" -> {
                    val actionId = payload.getString("action_id")
                    val version = payload.getInt("version")
                    val kind = payload.getString("kind")
                    val executor = payload.getString("executor")
                    val riskTier = payload.getInt("risk_tier")
                    val argsHash = payload.getString("args_hash")
                    val expiresAt = payload.getString("expires_at")
                    val requiresBiometric = payload.optBoolean("requires_biometric", false)

                    val previewJson = payload.getJSONObject("preview")
                    val title = previewJson.optString("title", "طلب اعتماد")
                    val app = previewJson.optString("app", "app.secretary")
                    val draftText = previewJson.optString("draft_text", "")

                    val recipientJson = previewJson.optJSONObject("recipient")
                    val recipient = if (recipientJson != null) {
                        ActionRecipient(
                            name = recipientJson.optString("name", "غير محدد"),
                            phone = if (recipientJson.has("phone") && !recipientJson.isNull("phone")) {
                                recipientJson.getString("phone")
                            } else null
                        )
                    } else null

                    val warningsJson = previewJson.optJSONArray("warnings") ?: JSONArray()
                    val warnings = mutableListOf<String>()
                    for (i in 0 until warningsJson.length()) {
                        warnings.add(warningsJson.getString(i))
                    }

                    val threadJson = previewJson.optJSONArray("thread_context") ?: JSONArray()
                    val threadContext = mutableListOf<ThreadMessage>()
                    for (i in 0 until threadJson.length()) {
                        val item = threadJson.getJSONObject(i)
                        threadContext.add(
                            ThreadMessage(
                                who = item.optString("who", ""),
                                text = item.optString("text", ""),
                                ts = item.optString("ts", "")
                            )
                        )
                    }

                    val preview = ActionPreview(
                        title = title,
                        app = app,
                        recipient = recipient,
                        threadContext = threadContext,
                        draftText = draftText,
                        warnings = warnings
                    )

                    _events.emit(
                        ServerWsEvent.ActionRequest(
                            actionId = actionId,
                            version = version,
                            kind = kind,
                            executor = executor,
                            riskTier = riskTier,
                            argsHash = argsHash,
                            expiresAt = expiresAt,
                            requiresBiometric = requiresBiometric,
                            preview = preview
                        )
                    )
                }
                "action_update" -> {
                    val actionId = payload.getString("action_id")
                    val version = payload.getInt("version")
                    val status = payload.getString("status")
                    val detail = if (payload.has("detail") && !payload.isNull("detail")) {
                        payload.getString("detail")
                    } else null
                    _events.emit(ServerWsEvent.ActionUpdate(actionId, version, status, detail))
                }
                "exec_command" -> {
                    val actionId = payload.getString("action_id")
                    val version = payload.getInt("version")
                    val kind = payload.optString("kind", "")
                    val args = payload.optJSONObject("args") ?: JSONObject()
                    _events.emit(ServerWsEvent.ExecCommand(actionId, version, kind, args))
                }
                "error" -> {
                    val code = payload.optString("code", "UNKNOWN_ERROR")
                    val message = payload.optString("message", "حدث خطأ غير متوقع")
                    _events.emit(ServerWsEvent.Error(code, message))
                }
            }
        }
    }
}
