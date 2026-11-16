package app.secretary

import android.Manifest
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import android.os.Bundle
import android.provider.Settings
import android.util.Log
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.ContentPaste
import androidx.compose.material.icons.filled.Dns
import androidx.compose.material.icons.filled.Image
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
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import androidx.lifecycle.lifecycleScope
import app.secretary.contacts.ContactsSyncManager
import app.secretary.core.network.PairingClient
import app.secretary.core.network.SanadWebSocketClient
import app.secretary.core.network.ServerWsEvent
import app.secretary.core.network.SessionManager
import app.secretary.gateway.RemoteInputGateway
import app.secretary.outbox.OutboxSyncWorker
import app.secretary.sensor.SmsSyncManager
import app.secretary.ui.ChatScreen
import app.secretary.ui.PoliciesScreen
import app.secretary.ui.theme.SanadTheme
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
    private var isNotificationAccessGranted by mutableStateOf(false)

    private val permissionsLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        val smsGranted = permissions[Manifest.permission.READ_SMS] == true ||
                permissions[Manifest.permission.RECEIVE_SMS] == true
        val contactsGranted = permissions[Manifest.permission.READ_CONTACTS] == true

        if (smsGranted || contactsGranted) {
            performFullSync()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        try {
            // جدولة المزامنة الدورية لصندوق الوارد
            OutboxSyncWorker.schedulePeriodicSync(this)
        } catch (_: Throwable) {}

        try {
            // فحص صلاحية قراءة الإشعارات
            checkNotificationAccess()
        } catch (_: Throwable) {}

        try {
            // اتصال تلقائي إذا كانت هناك جلسة مقترنة مسبقاً
            if (SessionManager.hasSession(this)) {
                connectWithSavedSession()
            }
        } catch (_: Throwable) {}

        setContent {
            // طلب الصلاحيات بأمان بعد اكتمال تهيئة واجهة المستخدم
            LaunchedEffect(Unit) {
                requestAppPermissions()
            }

            // توحيد نسق الواجهة RTL باللغة العربية لكامل التطبيق
            CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl) {
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
                                onSyncAll = {
                                    performFullSync()
                                },
                                isNotificationAccessGranted = isNotificationAccessGranted,
                                onOpenNotificationSettings = {
                                    startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
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
    }

    override fun onResume() {
        super.onResume()
        checkNotificationAccess()
    }

    private fun checkNotificationAccess() {
        try {
            val enabledListeners = androidx.core.app.NotificationManagerCompat.getEnabledListenerPackages(this)
            isNotificationAccessGranted = enabledListeners.contains(packageName)
        } catch (_: Throwable) {
            try {
                val flat = Settings.Secure.getString(contentResolver, "enabled_notification_listeners")
                isNotificationAccessGranted = flat != null && flat.contains(packageName)
            } catch (_: Throwable) {
                isNotificationAccessGranted = false
            }
        }
    }

    private fun requestAppPermissions() {
        try {
            val needed = mutableListOf<String>()

            val perms = arrayOf(
                Manifest.permission.READ_SMS,
                Manifest.permission.RECEIVE_SMS,
                Manifest.permission.READ_CONTACTS,
                Manifest.permission.POST_NOTIFICATIONS,
                Manifest.permission.RECORD_AUDIO,
                Manifest.permission.READ_PHONE_STATE
            )

            for (p in perms) {
                if (ContextCompat.checkSelfPermission(this, p) != PackageManager.PERMISSION_GRANTED) {
                    needed.add(p)
                }
            }

            if (needed.isNotEmpty()) {
                permissionsLauncher.launch(needed.toTypedArray())
            }
        } catch (_: Throwable) {}
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

        // مزامنة مبدئية عند استئناف الجلسة
        performFullSync()
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

                // بدء مزامنة الأحداث والرسائل وجهات الاتصال فوراً
                performFullSync()

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
                    if (event.kind == "send_notification_reply" || event.kind == "propose_reply") {
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

    fun performFullSync() {
        lifecycleScope.launch {
            try {
                // 1. مزامنة جهات الاتصال
                try {
                    ContactsSyncManager.syncDeviceContacts(this@MainActivity)
                } catch (_: Throwable) {}

                // 2. مزامنة الرسائل النصية القصيرة (SMS Inbox)
                try {
                    val smsResult = SmsSyncManager.syncInboxSms(this@MainActivity, limit = 50)
                    smsResult.onSuccess { count ->
                        if (count > 0) {
                            Toast.makeText(this@MainActivity, "تم تجهيز $count رسالة للمزامنة مع سند", Toast.LENGTH_SHORT).show()
                        }
                    }
                } catch (_: Throwable) {}

                // 3. إرسال الدفعة فوراً للخادم
                try {
                    OutboxSyncWorker.enqueueImmediateSync(this@MainActivity)
                } catch (_: Throwable) {}
            } catch (t: Throwable) {
                Log.e("MainActivity", "FullSync error", t)
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
                .build()
            GmsBarcodeScanning.getClient(context, options)
        } catch (_: Throwable) {
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
                    Toast.makeText(context, "تعذر قراءة ملف الصورة", Toast.LENGTH_SHORT).show()
                }
            } catch (e: Exception) {
                Toast.makeText(context, "فشل فحص الصورة: ${e.message}", Toast.LENGTH_SHORT).show()
            }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        text = "سند — ربط الهاتف",
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold
                    )
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface
                )
            )
        }
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
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
                text = "ربط الهاتف بسيرفر سند",
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onSurface
            )

            Spacer(modifier = Modifier.height(8.dp))

            Text(
                text = "افتح صفحة السيرفر في المتصفح وصوّر رمز الباركود المعروض، أو أدخل رمز الاقتران يدوياً.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = androidx.compose.ui.text.style.TextAlign.Center
            )

            Spacer(modifier = Modifier.height(28.dp))

            // زر مسح الباركود بالكاميرا (الأساسي والموصى به)
            Button(
                onClick = {
                    if (gmsScanner != null) {
                        try {
                            gmsScanner.startScan()
                                .addOnSuccessListener { barcode ->
                                    val raw = barcode.rawValue ?: barcode.displayValue
                                    if (!raw.isNullOrBlank()) {
                                        handleScannedPayload(raw)
                                    }
                                }
                                .addOnFailureListener { e ->
                                    Toast.makeText(context, "تعذر تشغيل الماسح: ${e.message}، يمكنك اختيار صورة الرمز من المعرض", Toast.LENGTH_LONG).show()
                                }
                        } catch (t: Throwable) {
                            Toast.makeText(context, "خطأ في خدمات Google Play: ${t.message}، يرجى اختيار الصورة من الاستوديو", Toast.LENGTH_LONG).show()
                            galleryPickerLauncher.launch("image/*")
                        }
                    } else {
                        Toast.makeText(context, "الماسح السريع غير متاح على هذا الجهاز، يرجى اختيار صورة الرمز من المعرض", Toast.LENGTH_LONG).show()
                        galleryPickerLauncher.launch("image/*")
                    }
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(54.dp),
                shape = MaterialTheme.shapes.medium
            ) {
                Icon(
                    imageVector = Icons.Default.QrCodeScanner,
                    contentDescription = null,
                    modifier = Modifier.size(24.dp)
                )
                Spacer(modifier = Modifier.width(10.dp))
                Text(
                    text = "مسح رمز الباركود (QR) بالكاميرا",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold
                )
            }

            Spacer(modifier = Modifier.height(12.dp))

            // زر بديل لاختيار صورة الباركود من المعرض
            OutlinedButton(
                onClick = {
                    galleryPickerLauncher.launch("image/*")
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(48.dp),
                shape = MaterialTheme.shapes.medium
            ) {
                Icon(
                    imageVector = Icons.Default.Image,
                    contentDescription = null,
                    modifier = Modifier.size(20.dp)
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = "اختيار صورة الباركود من الاستوديو",
                    style = MaterialTheme.typography.bodyMedium
                )
            }

            Spacer(modifier = Modifier.height(24.dp))

            // فاصل أو إدخال يدوي
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                HorizontalDivider(modifier = Modifier.weight(1f))
                Text(
                    text = " أو الإدخال اليدوي ",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                HorizontalDivider(modifier = Modifier.weight(1f))
            }

            Spacer(modifier = Modifier.height(20.dp))

            // حقل عنوان السيرفر
            OutlinedTextField(
                value = serverUrl,
                onValueChange = { serverUrl = it },
                label = { Text("عنوان الخادم (Server URL)") },
                placeholder = { Text("http://192.168.100.28:8000") },
                leadingIcon = {
                    Icon(
                        imageVector = Icons.Default.Dns,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary
                    )
                },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                shape = MaterialTheme.shapes.medium
            )

            Spacer(modifier = Modifier.height(14.dp))

            // حقل رمز الاقتران
            OutlinedTextField(
                value = pairingCode,
                onValueChange = { pairingCode = it.uppercase() },
                label = { Text("رمز الاقتران (16 حرفاً أو رقماً)") },
                placeholder = { Text("مثال: 4A8B9C1D2E3F4051") },
                leadingIcon = {
                    Icon(
                        imageVector = Icons.Default.Key,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary
                    )
                },
                trailingIcon = {
                    IconButton(onClick = {
                        val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                        val clip = clipboard.primaryClip
                        if (clip != null && clip.itemCount > 0) {
                            val pasted = clip.getItemAt(0).text?.toString() ?: ""
                            handleScannedPayload(pasted)
                        }
                    }) {
                        Icon(
                            imageVector = Icons.Default.ContentPaste,
                            contentDescription = "لصق من الحافظة",
                            tint = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                shape = MaterialTheme.shapes.medium
            )

            Spacer(modifier = Modifier.height(20.dp))

            FilledTonalButton(
                onClick = {
                    if (serverUrl.isBlank() || pairingCode.isBlank()) {
                        Toast.makeText(context, "يرجى إدخال عنوان السيرفر ورمز الاقتران", Toast.LENGTH_SHORT).show()
                    } else {
                        onPair(serverUrl, pairingCode)
                    }
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(50.dp),
                shape = MaterialTheme.shapes.medium,
                enabled = serverUrl.isNotBlank() && pairingCode.isNotBlank()
            ) {
                Icon(imageVector = Icons.Default.Link, contentDescription = null)
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = "إتمام الاقتران وحفظ الجلسة",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold
                )
            }

            Spacer(modifier = Modifier.height(24.dp))

            TextButton(onClick = { showAdvancedOptions = !showAdvancedOptions }) {
                Text(
                    text = if (showAdvancedOptions) "إخفاء الخيارات المتقدمة ▲" else "خيارات متقدمة ولصق كود QR يدوي ▼",
                    style = MaterialTheme.typography.labelLarge
                )
            }

            AnimatedVisibility(visible = showAdvancedOptions) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 12.dp)
                ) {
                    OutlinedTextField(
                        value = rawQrInput,
                        onValueChange = {
                            rawQrInput = it
                            if (it.contains("code") || it.length > 20) {
                                handleScannedPayload(it)
                            }
                        },
                        label = { Text("لصق محتوى رمز QR المباشر (JSON)") },
                        placeholder = { Text("{\"server_url\":\"...\",\"code\":\"...\"}") },
                        modifier = Modifier.fillMaxWidth(),
                        maxLines = 3,
                        shape = MaterialTheme.shapes.small
                    )

                    Spacer(modifier = Modifier.height(12.dp))

                    OutlinedButton(
                        onClick = onOpenSpikes,
                        modifier = Modifier.fillMaxWidth(),
                        shape = MaterialTheme.shapes.small
                    ) {
                        Icon(imageVector = Icons.Default.Build, contentDescription = null)
                        Spacer(modifier = Modifier.width(8.dp))
                        Text("لوحة القياس والتجارب الميدانية (Spikes)")
                    }
                }
            }
        }
    }
}

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
            Text(text = "معلومات اتصال السيرفر", fontWeight = FontWeight.Bold)
        },
        text = {
            Column {
                Text(text = "أنت مقترن حالياً بالخادم المنزلي:", style = MaterialTheme.typography.bodyMedium)
                Spacer(modifier = Modifier.height(6.dp))
                Surface(
                    color = MaterialTheme.colorScheme.surfaceVariant,
                    shape = MaterialTheme.shapes.small,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text(
                        text = serverUrl,
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(10.dp)
                    )
                }
                Spacer(modifier = Modifier.height(14.dp))
                Text(
                    text = "• قطع الاتصال: يوقف اتصال الـ WebSocket المؤقت.\n• إلغاء الاقتران: يحذف الجلسة المفاتيح ويتطلب مسح رمز باركود جديد.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) {
                Text("إغلاق")
            }
        },
        dismissButton = {
            Row {
                TextButton(onClick = onDisconnect) {
                    Text("قطع الاتصال")
                }
                Spacer(modifier = Modifier.width(4.dp))
                TextButton(
                    onClick = onUnpair,
                    colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error)
                ) {
                    Text("إلغاء الاقتران")
                }
            }
        }
    )
}
