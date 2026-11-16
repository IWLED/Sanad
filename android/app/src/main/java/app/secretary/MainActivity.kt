package app.secretary

import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.fragment.app.FragmentActivity
import androidx.lifecycle.lifecycleScope
import app.secretary.contacts.ContactsSyncManager
import app.secretary.core.network.PairingClient
import app.secretary.core.network.SanadWebSocketClient
import app.secretary.core.network.ServerWsEvent
import app.secretary.core.network.SessionManager
import app.secretary.gateway.RemoteInputGateway
import app.secretary.outbox.OutboxSyncWorker
import app.secretary.ui.ChatScreen
import app.secretary.ui.PoliciesScreen
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import org.json.JSONObject

class MainActivity : FragmentActivity() {

    private val keystoreManager by lazy { app.secretary.core.security.AndroidKeystoreManager() }
    private var activeWsClient by mutableStateOf<SanadWebSocketClient?>(null)
    private var execCommandsJob: Job? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // جدولة المزامنة الدورية لصندوق الوارد
        OutboxSyncWorker.schedulePeriodicSync(this)

        setContent {
            MaterialTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    var showPoliciesScreen by remember { mutableStateOf(false) }
                    val wsClient = activeWsClient
                    if (wsClient != null) {
                        ChatScreen(
                            wsClient = wsClient,
                            onBack = {
                                wsClient.disconnect()
                                execCommandsJob?.cancel()
                                activeWsClient = null
                            }
                        )
                    } else if (showPoliciesScreen) {
                        val serverUrl = SessionManager.getServerUrl(this)
                        val token = SessionManager.getAccessToken(this) ?: ""
                        PoliciesScreen(
                            serverUrl = serverUrl,
                            token = token,
                            onBack = { showPoliciesScreen = false }
                        )
                    } else {
                        HomeScreen(
                            hasSavedSession = SessionManager.hasSession(this),
                            savedServerUrl = SessionManager.getServerUrl(this),
                            onOpenSpikes = {
                                startActivity(Intent(this, SpikeActivity::class.java))
                            },
                            onPairAndConnect = { serverUrl, code ->
                                performPairing(serverUrl, code)
                            },
                            onReconnectSaved = {
                                connectWithSavedSession()
                            },
                            onSyncContacts = {
                                performContactsSync()
                            },
                            onOpenPolicies = {
                                showPoliciesScreen = true
                            }
                        )
                    }
                }
            }
        }
    }

    private fun connectWithSavedSession() {
        val serverUrl = SessionManager.getServerUrl(this)
        val token = SessionManager.getAccessToken(this)
        if (token == null) {
            Toast.makeText(this, "لا توجد جلسة محفوظة", Toast.LENGTH_SHORT).show()
            return
        }

        val wsClient = SanadWebSocketClient(
            serverUrl = serverUrl.trimEnd('/'),
            token = token
        )
        wsClient.connect()
        activeWsClient = wsClient
        listenForExecCommands(wsClient)
    }

    private fun performPairing(serverUrl: String, code: String) {
        lifecycleScope.launch {
            val pairingClient = PairingClient(
                serverBaseUrl = serverUrl.trimEnd('/'),
                keystoreManager = keystoreManager
            )

            val result = pairingClient.pair(code = code.trim())
            result.onSuccess { session ->
                Toast.makeText(this@MainActivity, "تم الاقتران بنجاح!", Toast.LENGTH_SHORT).show()
                SessionManager.saveSession(
                    this@MainActivity,
                    serverUrl = serverUrl.trimEnd('/'),
                    deviceId = session.deviceId,
                    accessToken = session.accessToken,
                    refreshToken = session.refreshToken
                )

                // بدء مزامنة الأحداث فورا
                OutboxSyncWorker.enqueueImmediateSync(this@MainActivity)

                val wsClient = SanadWebSocketClient(
                    serverUrl = serverUrl.trimEnd('/'),
                    token = session.accessToken
                )
                wsClient.connect()
                activeWsClient = wsClient
                listenForExecCommands(wsClient)
            }.onFailure { error ->
                Toast.makeText(this@MainActivity, "فشل الاقتران: ${error.message}", Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun listenForExecCommands(wsClient: SanadWebSocketClient) {
        execCommandsJob?.cancel()
        execCommandsJob = lifecycleScope.launch {
            wsClient.events.collect { event ->
                if (event is ServerWsEvent.ExecCommand) {
                    if (event.kind == "send_notification_reply") {
                        val text = event.args.optString("text", "")
                        val key = event.args.optString("thread_key", "")
                        val success = RemoteInputGateway.sendReply(this@MainActivity, key, text)
                        wsClient.sendDeviceExecResult(
                            actionId = event.actionId,
                            version = event.version,
                            status = if (success) "success" else "failed",
                            detail = if (success) "Dispatched via RemoteInput" else "Action key not found in active notifications"
                        )
                    }
                }
            }
        }
    }

    private fun performContactsSync() {
        lifecycleScope.launch {
            Toast.makeText(this@MainActivity, "جارِ مزامنة جهات الاتصال...", Toast.LENGTH_SHORT).show()
            val res = ContactsSyncManager.syncDeviceContacts(this@MainActivity)
            res.onSuccess { count ->
                Toast.makeText(this@MainActivity, "تمت مزامنة $count جهة اتصال بنجاح!", Toast.LENGTH_LONG).show()
            }.onFailure { err ->
                Toast.makeText(this@MainActivity, "فشلت المزامنة: ${err.message}", Toast.LENGTH_LONG).show()
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        execCommandsJob?.cancel()
        activeWsClient?.disconnect()
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    hasSavedSession: Boolean,
    savedServerUrl: String,
    onOpenSpikes: () -> Unit,
    onPairAndConnect: (serverUrl: String, code: String) -> Unit,
    onReconnectSaved: () -> Unit,
    onSyncContacts: () -> Unit,
    onOpenPolicies: () -> Unit
) {
    var serverUrl by remember { mutableStateOf(savedServerUrl) }
    var pairingCode by remember { mutableStateOf("") }
    var rawQrInput by remember { mutableStateOf("") }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("سند — السكرتير الشخصي الذكي", fontWeight = FontWeight.Bold) }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(20.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Top
        ) {
            if (hasSavedSession) {
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(16.dp),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.primaryContainer
                    )
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text(
                            text = "الجهاز مقترن مسبقاً",
                            fontWeight = FontWeight.Bold,
                            fontSize = 16.sp
                        )
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = "الخادم: $savedServerUrl",
                            fontSize = 13.sp
                        )
                        Spacer(modifier = Modifier.height(12.dp))
                        Button(
                            onClick = onReconnectSaved,
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text("فتح جلسة المحادثة (WebSocket)")
                        }
                        Spacer(modifier = Modifier.height(8.dp))
                        OutlinedButton(
                            onClick = onSyncContacts,
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text("مزامنة جهات الاتصال مع الخادم")
                        }
                        Spacer(modifier = Modifier.height(8.dp))
                        OutlinedButton(
                            onClick = onOpenPolicies,
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text("إعدادات سياسات التطبيقات والردود")
                        }
                    }
                }
                Spacer(modifier = Modifier.height(16.dp))
            }

            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(16.dp),
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant
                )
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(
                        text = "اقتران جديد بالخادم (New Pairing)",
                        fontWeight = FontWeight.Bold,
                        fontSize = 16.sp
                    )
                    Spacer(modifier = Modifier.height(12.dp))

                    OutlinedTextField(
                        value = serverUrl,
                        onValueChange = { serverUrl = it },
                        label = { Text("رابط الخادم (Server URL)") },
                        modifier = Modifier.fillMaxWidth()
                    )

                    Spacer(modifier = Modifier.height(8.dp))

                    OutlinedTextField(
                        value = pairingCode,
                        onValueChange = { pairingCode = it },
                        label = { Text("رمز الاقتران (128-bit Code)") },
                        modifier = Modifier.fillMaxWidth()
                    )

                    Spacer(modifier = Modifier.height(10.dp))

                    Text(
                        text = "أو الصق حمولة QR كاملة أدناه:",
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f)
                    )

                    Spacer(modifier = Modifier.height(4.dp))

                    OutlinedTextField(
                        value = rawQrInput,
                        onValueChange = { input ->
                            rawQrInput = input
                            try {
                                val json = JSONObject(input.trim())
                                if (json.has("server_url")) serverUrl = json.getString("server_url")
                                if (json.has("code")) pairingCode = json.getString("code")
                            } catch (_: Exception) {}
                        },
                        placeholder = { Text("{\"server_url\": \"...\", \"code\": \"...\"}") },
                        modifier = Modifier.fillMaxWidth(),
                        maxLines = 2
                    )

                    Spacer(modifier = Modifier.height(16.dp))

                    Button(
                        onClick = {
                            if (serverUrl.isNotBlank() && pairingCode.isNotBlank()) {
                                onPairAndConnect(serverUrl, pairingCode)
                            }
                        },
                        modifier = Modifier.fillMaxWidth(),
                        enabled = serverUrl.isNotBlank() && pairingCode.isNotBlank()
                    ) {
                        Text("اقتران جديد")
                    }
                }
            }

            Spacer(modifier = Modifier.height(24.dp))

            OutlinedButton(
                onClick = onOpenSpikes,
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("فتح أداة التجارب الميدانية (Spikes S1-S5)")
            }
        }
    }
}
