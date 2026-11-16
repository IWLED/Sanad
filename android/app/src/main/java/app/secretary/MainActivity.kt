package app.secretary

import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.Dns
import androidx.compose.material.icons.filled.Key
import androidx.compose.material.icons.filled.Link
import androidx.compose.material.icons.filled.QrCode
import androidx.compose.material.icons.filled.QrCodeScanner
import androidx.compose.material.icons.filled.SmartToy
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
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
import app.secretary.ui.theme.SanadTheme
import android.content.ClipboardManager
import android.content.Context
import android.graphics.BitmapFactory
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material.icons.filled.ContentPaste
import androidx.compose.material.icons.filled.Image
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import com.google.zxing.BinaryBitmap
import com.google.zxing.MultiFormatReader
import com.google.zxing.RGBLuminanceSource
import com.google.zxing.common.HybridBinarizer
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

        // اتصال تلقائي إذا كانت هناك جلسة مقترنة مسبقاً
        if (SessionManager.hasSession(this)) {
            connectWithSavedSession()
        }

        setContent {
            SanadTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    var showPoliciesScreen by remember { mutableStateOf(false) }
                    var showServerDetailsDialog by remember { mutableStateOf(false) }
                    val wsClient = activeWsClient

                    if (wsClient != null) {
                        ChatScreen(
                            wsClient = wsClient,
                            onBack = {
                                showServerDetailsDialog = true
                            },
                            onOpenPolicies = {
                                showPoliciesScreen = true
                            },
                            onSyncContacts = {
                                performContactsSync()
                            }
                        )

                        if (showServerDetailsDialog) {
                            ServerInfoDialog(
                                serverUrl = wsClient.serverUrl,
                                onDismiss = { showServerDetailsDialog = false },
                                onDisconnect = {
                                    wsClient.disconnect()
                                    execCommandsJob?.cancel()
                                    activeWsClient = null
                                    showServerDetailsDialog = false
                                },
                                onUnpair = {
                                    wsClient.disconnect()
                                    execCommandsJob?.cancel()
                                    activeWsClient = null
                                    SessionManager.clearSession(this)
                                    showServerDetailsDialog = false
                                    Toast.makeText(this, "تم إلغاء اقتران الجهاز بنجاح", Toast.LENGTH_SHORT).show()
                                }
                            )
                        }
                    } else if (showPoliciesScreen) {
                        val serverUrl = SessionManager.getServerUrl(this)
                        val token = SessionManager.getAccessToken(this) ?: ""
                        PoliciesScreen(
                            serverUrl = serverUrl,
                            token = token,
                            onBack = { showPoliciesScreen = false }
                        )
                    } else {
                        PairingScreen(
                            savedServerUrl = SessionManager.getServerUrl(this),
                            onPair = { serverUrl, code ->
                                performPairing(serverUrl, code)
                            },
                            onOpenSpikes = {
                                startActivity(Intent(this, SpikeActivity::class.java))
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
        if (token == null || serverUrl.isBlank()) return

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

                // بدء مزامنة الأحداث فوراً
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
            Toast.makeText(this@MainActivity, "جارِ مزامنة جهات الاتصال مع الخادم...", Toast.LENGTH_SHORT).show()
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

/**
 * شاشة الاقتران والترحيب الرئيسية عند الإعداد أو إعادة الربط.
 * مصممة وفق أحدث معايير Material 3 بأسلوب واضح ومريح.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PairingScreen(
    savedServerUrl: String,
    onPair: (serverUrl: String, code: String) -> Unit,
    onOpenSpikes: () -> Unit
) {
    val context = LocalContext.current
    val defaultUrl = if (savedServerUrl.isNotBlank()) savedServerUrl else "http://192.168.100.28:8000"
    var serverUrl by remember { mutableStateOf(defaultUrl) }
    var pairingCode by remember { mutableStateOf("") }
    var showAdvancedOptions by remember { mutableStateOf(false) }
    var rawQrInput by remember { mutableStateOf("") }

    fun handleScannedPayload(payload: String) {
        val clean = payload.trim()
        try {
            val json = JSONObject(clean)
            val parsedUrl = json.optString("server_url", "")
            val parsedCode = json.optString("code", "")
            if (parsedCode.isNotBlank()) {
                val targetUrl = if (parsedUrl.isNotBlank()) parsedUrl else serverUrl
                pairingCode = parsedCode.uppercase()
                serverUrl = targetUrl
                onPair(targetUrl, parsedCode.uppercase())
                return
            }
        } catch (_: Exception) {}

        val codeOnly = clean.replace(" ", "").replace("-", "").uppercase()
        pairingCode = codeOnly
        if (serverUrl.isNotBlank()) {
            onPair(serverUrl, codeOnly)
        }
    }

    val gmsScanner = remember {
        try {
            val options = GmsBarcodeScannerOptions.Builder()
                .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
                .enableAutoZoom()
                .build()
            GmsBarcodeScanning.getClient(context, options)
        } catch (_: Exception) {
            null
        }
    }

    val galleryPickerLauncher = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) {
            try {
                val inputStream = context.contentResolver.openInputStream(uri)
                val bitmap = BitmapFactory.decodeStream(inputStream)
                inputStream?.close()
                if (bitmap != null) {
                    val intArray = IntArray(bitmap.width * bitmap.height)
                    bitmap.getPixels(intArray, 0, bitmap.width, 0, 0, bitmap.width, bitmap.height)
                    val source = RGBLuminanceSource(bitmap.width, bitmap.height, intArray)
                    val binaryBitmap = BinaryBitmap(HybridBinarizer(source))
                    val result = MultiFormatReader().decode(binaryBitmap)
                    val text = result?.text
                    if (!text.isNullOrBlank()) {
                        Toast.makeText(context, "تم مسح الرمز من الصورة بنجاح!", Toast.LENGTH_SHORT).show()
                        handleScannedPayload(text)
                    } else {
                        Toast.makeText(context, "لم يتم العثور على رمز QR صالح في الصورة", Toast.LENGTH_LONG).show()
                    }
                } else {
                    Toast.makeText(context, "تعذر قراءة الصورة المختارة", Toast.LENGTH_SHORT).show()
                }
            } catch (e: Exception) {
                Toast.makeText(context, "تعذر فك شفرة الصورة: تأكد من وضوح رمز الـ QR", Toast.LENGTH_LONG).show()
            }
        }
    }

    Scaffold(
        topBar = {
            CenterAlignedTopAppBar(
                title = {
                    Text(
                        "سند",
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold
                    )
                },
                colors = TopAppBarDefaults.centerAlignedTopAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface
                )
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Surface(
                shape = CircleShape,
                color = MaterialTheme.colorScheme.primaryContainer,
                modifier = Modifier.size(72.dp)
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Icon(
                        imageVector = Icons.Default.SmartToy,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onPrimaryContainer,
                        modifier = Modifier.size(36.dp)
                    )
                }
            }

            Spacer(modifier = Modifier.height(16.dp))

            Text(
                text = "السكرتير الشخصي الذكي",
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onSurface
            )

            Spacer(modifier = Modifier.height(6.dp))

            Text(
                text = "اربط جهازك بخادمك المنزلي لبدء إدارة المواعيد، الإيجاز اليومي، والرسائل بأعلى درجات الخصوصية.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = androidx.compose.ui.text.style.TextAlign.Center
            )

            Spacer(modifier = Modifier.height(28.dp))

            // بطاقة بيانات الاقتران
            ElevatedCard(
                modifier = Modifier.fillMaxWidth(),
                shape = MaterialTheme.shapes.large,
                colors = CardDefaults.elevatedCardColors(
                    containerColor = MaterialTheme.colorScheme.surface
                ),
                elevation = CardDefaults.elevatedCardElevation(defaultElevation = 2.dp)
            ) {
                Column(modifier = Modifier.padding(20.dp)) {
                    Text(
                        text = "طرق الاقتران السريع",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.onSurface
                    )

                    Spacer(modifier = Modifier.height(16.dp))

                    // خيار المسح المباشر عبر الكاميرا (Google Code Scanner الآمن والمستقر تماماً)
                    Button(
                        onClick = {
                            if (gmsScanner != null) {
                                try {
                                    gmsScanner.startScan()
                                        .addOnSuccessListener { barcode ->
                                            val raw = barcode.rawValue ?: barcode.displayValue ?: ""
                                            if (raw.isNotBlank()) {
                                                handleScannedPayload(raw)
                                            }
                                        }
                                        .addOnCanceledListener {
                                            // تم إلغاء المسح بأمان
                                        }
                                        .addOnFailureListener { error ->
                                            Toast.makeText(context, "تعذر تشغيل الكاميرا التلقائية: ${error.localizedMessage ?: "حدث خطأ"}", Toast.LENGTH_LONG).show()
                                        }
                                } catch (e: Exception) {
                                    Toast.makeText(context, "خطأ في تشغيل الكاميرا: ${e.localizedMessage}", Toast.LENGTH_LONG).show()
                                }
                            } else {
                                Toast.makeText(context, "خدمة المسح بالكاميرا غير متاحة، يرجى اختيار الصورة من المعرض أو الإدخال اليدوي", Toast.LENGTH_LONG).show()
                            }
                        },
                        modifier = Modifier.fillMaxWidth(),
                        shape = MaterialTheme.shapes.medium,
                        contentPadding = PaddingValues(vertical = 14.dp)
                    ) {
                        Icon(
                            imageVector = Icons.Default.QrCodeScanner,
                            contentDescription = null,
                            modifier = Modifier.size(22.dp)
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            "مسح رمز الـ QR من شاشة السيرفر",
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.Bold
                        )
                    }

                    Spacer(modifier = Modifier.height(10.dp))

                    // خيار اختيار صورة الـ QR من معرض الصور كبديل مضمون 100%
                    OutlinedButton(
                        onClick = {
                            try {
                                galleryPickerLauncher.launch("image/*")
                            } catch (e: Exception) {
                                Toast.makeText(context, "تعذر فتح المعرض: ${e.localizedMessage}", Toast.LENGTH_SHORT).show()
                            }
                        },
                        modifier = Modifier.fillMaxWidth(),
                        shape = MaterialTheme.shapes.medium,
                        contentPadding = PaddingValues(vertical = 12.dp)
                    ) {
                        Icon(
                            imageVector = Icons.Default.Image,
                            contentDescription = null,
                            modifier = Modifier.size(20.dp)
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            "أو اختيار صورة الـ QR من المعرض",
                            style = MaterialTheme.typography.labelLarge
                        )
                    }

                    Spacer(modifier = Modifier.height(18.dp))

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        HorizontalDivider(modifier = Modifier.weight(1f))
                        Text(
                            text = "  أو الإدخال اليدوي للرمز  ",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        HorizontalDivider(modifier = Modifier.weight(1f))
                    }

                    Spacer(modifier = Modifier.height(16.dp))

                    OutlinedTextField(
                        value = serverUrl,
                        onValueChange = { serverUrl = it },
                        label = { Text("عنوان الخادم (Server URL)") },
                        leadingIcon = {
                            Icon(
                                imageVector = Icons.Default.Dns,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.primary
                            )
                        },
                        modifier = Modifier.fillMaxWidth(),
                        shape = MaterialTheme.shapes.medium,
                        singleLine = true
                    )

                    Spacer(modifier = Modifier.height(14.dp))

                    OutlinedTextField(
                        value = pairingCode,
                        onValueChange = { pairingCode = it },
                        label = { Text("رمز الاقتران (Pairing Code)") },
                        placeholder = { Text("أدخل الرمز الظاهر على السيرفر") },
                        leadingIcon = {
                            Icon(
                                imageVector = Icons.Default.Key,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.primary
                            )
                        },
                        trailingIcon = {
                            IconButton(onClick = {
                                val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
                                val clip = clipboard?.primaryClip?.getItemAt(0)?.text?.toString()
                                if (!clip.isNullOrBlank()) {
                                    pairingCode = clip.trim().replace(" ", "").replace("-", "").uppercase()
                                    Toast.makeText(context, "تم لصق الرمز من الحافظة!", Toast.LENGTH_SHORT).show()
                                } else {
                                    Toast.makeText(context, "الحافظة فارغة", Toast.LENGTH_SHORT).show()
                                }
                            }) {
                                Icon(
                                    imageVector = Icons.Default.ContentPaste,
                                    contentDescription = "لصق من الحافظة",
                                    tint = MaterialTheme.colorScheme.primary
                                )
                            }
                        },
                        modifier = Modifier.fillMaxWidth(),
                        shape = MaterialTheme.shapes.medium,
                        singleLine = true
                    )

                    Spacer(modifier = Modifier.height(20.dp))

                    Button(
                        onClick = {
                            val cleanCode = pairingCode.trim().replace(" ", "").replace("-", "").uppercase()
                            if (serverUrl.isNotBlank() && cleanCode.isNotBlank()) {
                                onPair(serverUrl.trim(), cleanCode)
                            }
                        },
                        modifier = Modifier.fillMaxWidth(),
                        enabled = serverUrl.isNotBlank() && pairingCode.isNotBlank(),
                        shape = MaterialTheme.shapes.medium,
                        contentPadding = PaddingValues(vertical = 12.dp)
                    ) {
                        Icon(
                            imageVector = Icons.Default.Link,
                            contentDescription = null,
                            modifier = Modifier.size(20.dp)
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            "ربط واقتران بالخادم",
                            style = MaterialTheme.typography.labelLarge,
                            fontWeight = FontWeight.Bold
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(20.dp))

            // قسم الخيارات المتقدمة (QR Code / Spikes)
            TextButton(
                onClick = { showAdvancedOptions = !showAdvancedOptions },
                shape = MaterialTheme.shapes.small
            ) {
                Icon(
                    imageVector = Icons.Default.Build,
                    contentDescription = null,
                    modifier = Modifier.size(16.dp)
                )
                Spacer(modifier = Modifier.width(6.dp))
                Text(
                    text = if (showAdvancedOptions) "إخفاء الخيارات الإضافية" else "خيارات متقدمة (QR / فحص)",
                    style = MaterialTheme.typography.labelMedium
                )
            }

            AnimatedVisibility(visible = showAdvancedOptions) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 10.dp)
                ) {
                    OutlinedCard(
                        modifier = Modifier.fillMaxWidth(),
                        shape = MaterialTheme.shapes.medium,
                        colors = CardDefaults.outlinedCardColors(
                            containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.35f)
                        )
                    ) {
                        Column(modifier = Modifier.padding(16.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Icon(
                                    imageVector = Icons.Default.QrCode,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.primary,
                                    modifier = Modifier.size(18.dp)
                                )
                                Spacer(modifier = Modifier.width(8.dp))
                                Text(
                                    text = "لصق حمولة QR كاملة (اختياري)",
                                    style = MaterialTheme.typography.titleSmall,
                                    fontWeight = FontWeight.SemiBold
                                )
                            }

                            Spacer(modifier = Modifier.height(8.dp))

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
                                shape = MaterialTheme.shapes.small,
                                maxLines = 2
                            )

                            Spacer(modifier = Modifier.height(14.dp))

                            OutlinedButton(
                                onClick = onOpenSpikes,
                                modifier = Modifier.fillMaxWidth(),
                                shape = MaterialTheme.shapes.small
                            ) {
                                Text("أداة القياس الميداني (Spikes)", style = MaterialTheme.typography.labelMedium)
                            }
                        }
                    }
                }
            }
        }
    }
}

/**
 * حوار عرض معلومات الخادم وخيارات إلغاء الاقتران أو فصل الجلسة.
 */
@Composable
fun ServerInfoDialog(
    serverUrl: String,
    onDismiss: () -> Unit,
    onDisconnect: () -> Unit,
    onUnpair: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Text(
                "معلومات خادم سند",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold
            )
        },
        text = {
            Column {
                Text(
                    text = "الخادم المتصل حالياً:",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = serverUrl,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.primary
                )
                Spacer(modifier = Modifier.height(12.dp))
                Text(
                    text = "يمكنك قطع الاتصال المؤقت بالجلسة أو إلغاء اقتران الهاتف بالكامل لإعادة ربطه مع خادم آخر.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        },
        confirmButton = {
            Button(
                onClick = onDisconnect,
                shape = MaterialTheme.shapes.small
            ) {
                Text("فصل الجلسة")
            }
        },
        dismissButton = {
            TextButton(
                onClick = onUnpair,
                shape = MaterialTheme.shapes.small,
                colors = ButtonDefaults.textButtonColors(
                    contentColor = MaterialTheme.colorScheme.error
                )
            ) {
                Text("إلغاء الاقتران")
            }
        }
    )
}
