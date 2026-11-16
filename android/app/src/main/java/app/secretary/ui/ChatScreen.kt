package app.secretary.ui

import android.Manifest
import android.content.pm.PackageManager
import android.net.Uri
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Dns
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.NotificationsActive
import androidx.compose.material.icons.filled.Security
import androidx.compose.material.icons.filled.SmartToy
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import app.secretary.core.audio.AudioRecordManager
import app.secretary.core.network.ConnectionStatus
import app.secretary.core.network.FileUploadManager
import app.secretary.core.network.SanadWebSocketClient
import app.secretary.core.network.ServerWsEvent
import app.secretary.core.network.UploadedFileMeta
import app.secretary.ui.theme.StatusCritical
import app.secretary.ui.theme.StatusSuccess
import app.secretary.ui.theme.StatusWarning
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import org.json.JSONObject

sealed interface ChatItem {
    data class UserMessage(val id: String, val text: String, val ts: String) : ChatItem
    data class AssistantMessage(val id: String, val text: String, val ts: String) : ChatItem
    data class HitlAction(val request: ServerWsEvent.ActionRequest, val status: String? = null) : ChatItem
    data class BriefingAttachment(val briefingId: String, val title: String, val renderedText: String, val isAcked: Boolean = false) : ChatItem
    data class FileAttachment(val fileId: String, val filename: String, val sizeBytes: Long, val mimeType: String) : ChatItem
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    wsClient: SanadWebSocketClient,
    onBack: () -> Unit,
    onOpenPolicies: () -> Unit,
    onSyncAll: () -> Unit,
    isNotificationAccessGranted: Boolean,
    onOpenNotificationSettings: () -> Unit,
    modifier: Modifier = Modifier
) {
    val context = LocalContext.current
    val coroutineScope = rememberCoroutineScope()
    val listState = rememberLazyListState()
    val connectionStatus by wsClient.connectionStatus.collectAsState()
    var inputText by remember { mutableStateOf("") }
    val chatItems = remember { mutableStateListOf<ChatItem>() }

    var pendingAttachment by remember { mutableStateOf<UploadedFileMeta?>(null) }
    var isUploadingFile by remember { mutableStateOf(false) }

    val audioManager = remember { AudioRecordManager(context) }
    var isRecording by remember { mutableStateOf(false) }
    var isTranscribing by remember { mutableStateOf(false) }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) {
            val started = audioManager.startRecording()
            isRecording = started
            if (!started) {
                Toast.makeText(context, "تعذر بدء التسجيل الصوتي", Toast.LENGTH_SHORT).show()
            }
        } else {
            Toast.makeText(context, "يلزم منح إذن الميكروفون للتسجيل الصوتي", Toast.LENGTH_SHORT).show()
        }
    }

    val filePickerLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri: Uri? ->
        if (uri != null) {
            isUploadingFile = true
            coroutineScope.launch {
                val res = FileUploadManager.uploadFile(
                    context = context,
                    serverUrl = wsClient.serverUrl,
                    token = wsClient.token,
                    uri = uri
                )
                isUploadingFile = false
                res.onSuccess { meta ->
                    pendingAttachment = meta
                    Toast.makeText(context, "تم إرفاق المستند: ${meta.filename}", Toast.LENGTH_SHORT).show()
                }.onFailure { err ->
                    Toast.makeText(context, "فشل رفع الملف: ${err.message}", Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    // التمرير التلقائي لآخر رسالة
    LaunchedEffect(chatItems.size) {
        if (chatItems.isNotEmpty()) {
            listState.animateScrollToItem(chatItems.size - 1)
        }
    }

    // الاستماع لأحداث WebSocket القادمة من الخادم
    LaunchedEffect(wsClient) {
        wsClient.events.collectLatest { event ->
            when (event) {
                is ServerWsEvent.AssistantMessage -> {
                    chatItems.add(
                        ChatItem.AssistantMessage(
                            id = System.currentTimeMillis().toString(),
                            text = event.text,
                            ts = "الآن"
                        )
                    )

                    // كشف إن كان الرد يحتوي على رابط ملف مولد
                    val fileRegex = Regex("""/v1/files/(fil_[a-f0-9]+|file_[a-f0-9]+)/download""")
                    val match = fileRegex.find(event.text)
                    if (match != null) {
                        val fileId = match.groupValues[1]
                        val filename = when {
                            event.text.contains(".docx") -> "$fileId.docx"
                            event.text.contains(".xlsx") -> "$fileId.xlsx"
                            event.text.contains(".pptx") -> "$fileId.pptx"
                            event.text.contains(".pdf") -> "$fileId.pdf"
                            else -> "$fileId.bin"
                        }
                        val mime = when {
                            filename.endsWith(".docx") -> "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                            filename.endsWith(".xlsx") -> "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                            filename.endsWith(".pptx") -> "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                            filename.endsWith(".pdf") -> "application/pdf"
                            else -> "application/octet-stream"
                        }
                        chatItems.add(
                            ChatItem.FileAttachment(
                                fileId = fileId,
                                filename = filename,
                                sizeBytes = 0L,
                                mimeType = mime
                            )
                        )
                    }
                }
                is ServerWsEvent.ActionRequest -> {
                    chatItems.add(ChatItem.HitlAction(request = event))
                }
                is ServerWsEvent.ActionUpdate -> {
                    val index = chatItems.indexOfFirst {
                        it is ChatItem.HitlAction && it.request.actionId == event.actionId
                    }
                    if (index != -1) {
                        val current = chatItems[index] as ChatItem.HitlAction
                        chatItems[index] = current.copy(status = event.status)
                    }
                }
                is ServerWsEvent.BriefingReady -> {
                    chatItems.add(
                        ChatItem.BriefingAttachment(
                            briefingId = event.briefingId,
                            title = event.title,
                            renderedText = event.renderedText
                        )
                    )
                }
                is ServerWsEvent.ReminderAlert -> {
                    val alertText = "⏰ تذكير موعد:\n${event.title}" + (if (!event.notes.isNullOrBlank()) "\nملاحظات: ${event.notes}" else "")
                    chatItems.add(
                        ChatItem.AssistantMessage(
                            id = System.currentTimeMillis().toString(),
                            text = alertText,
                            ts = "الآن"
                        )
                    )
                }
                is ServerWsEvent.Error -> {
                    Toast.makeText(context, "تنبيه: ${event.message}", Toast.LENGTH_LONG).show()
                }
                else -> Unit
            }
        }
    }

    fun authenticateWithBiometrics(onSuccess: () -> Unit) {
        val activity = context as? FragmentActivity
        if (activity == null) {
            onSuccess()
            return
        }

        val executor = ContextCompat.getMainExecutor(activity)
        val prompt = BiometricPrompt(
            activity,
            executor,
            object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    super.onAuthenticationSucceeded(result)
                    onSuccess()
                }

                override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                    super.onAuthenticationError(errorCode, errString)
                    Toast.makeText(context, "فشل التحقق الحيوي: $errString", Toast.LENGTH_SHORT).show()
                }
            }
        )

        val promptInfo = BiometricPrompt.PromptInfo.Builder()
            .setTitle("تأكيد العملية الحساسة")
            .setSubtitle("يتطلب الإجراء بصمة حيوية صريحة للاعتماد (Tier 3)")
            .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG or BiometricManager.Authenticators.DEVICE_CREDENTIAL)
            .build()

        prompt.authenticate(promptInfo)
    }

    fun handleSendMessage() {
        val text = inputText.trim()
        val currentAtt = pendingAttachment

        if (text.isEmpty() && currentAtt == null) return

        val attachmentsList = if (currentAtt != null) {
            listOf(
                JSONObject().apply {
                    put("file_id", currentAtt.fileId)
                    put("filename", currentAtt.filename)
                    put("size_bytes", currentAtt.sizeBytes)
                    put("mime_type", currentAtt.mimeType)
                    if (!currentAtt.extractedText.isNullOrEmpty()) {
                        put("extracted_text", currentAtt.extractedText)
                    }
                }
            )
        } else emptyList()

        val displayText = when {
            text.isNotEmpty() && currentAtt != null -> "$text\n📎 [مرفق: ${currentAtt.filename}]"
            currentAtt != null -> "📎 [مرفق مستند: ${currentAtt.filename}]"
            else -> text
        }

        chatItems.add(
            ChatItem.UserMessage(
                id = System.currentTimeMillis().toString(),
                text = displayText,
                ts = "الآن"
            )
        )

        if (currentAtt != null) {
            chatItems.add(
                ChatItem.FileAttachment(
                    fileId = currentAtt.fileId,
                    filename = currentAtt.filename,
                    sizeBytes = currentAtt.sizeBytes,
                    mimeType = currentAtt.mimeType
                )
            )
        }

        wsClient.sendUserMessage(text, attachments = attachmentsList)
        inputText = ""
        pendingAttachment = null
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                text = "سند",
                                style = MaterialTheme.typography.titleLarge,
                                fontWeight = FontWeight.Bold
                            )
                            Spacer(modifier = Modifier.width(8.dp))
                            val (dotColor, statusText) = when (connectionStatus) {
                                ConnectionStatus.CONNECTED -> Pair(StatusSuccess, "متصل")
                                ConnectionStatus.CONNECTING -> Pair(StatusWarning, "جاري الاتصال...")
                                ConnectionStatus.DISCONNECTED -> Pair(StatusCritical, "غير متصل")
                            }
                            Box(
                                modifier = Modifier
                                    .size(8.dp)
                                    .clip(CircleShape)
                                    .background(dotColor)
                            )
                            Spacer(modifier = Modifier.width(6.dp))
                            Text(
                                text = statusText,
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        Text(
                            text = "السكرتير الشخصي الذكي",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f)
                        )
                    }
                },
                actions = {
                    IconButton(onClick = onSyncAll) {
                        Icon(
                            imageVector = Icons.Default.Sync,
                            contentDescription = "مزامنة الرسائل وجهات الاتصال",
                            tint = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    IconButton(onClick = onOpenPolicies) {
                        Icon(
                            imageVector = Icons.Default.Security,
                            contentDescription = "سياسات التطبيقات والردود",
                            tint = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    IconButton(onClick = onBack) {
                        Icon(
                            imageVector = Icons.Default.Dns,
                            contentDescription = "معلومات الاتصال بالخادم",
                            tint = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface
                )
            )
        },
        modifier = modifier
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
        ) {
            // تنبيه عدم تفعيل قراءة الإشعارات (واتساب وغيرها)
            if (!isNotificationAccessGranted) {
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.8f)
                    ),
                    shape = MaterialTheme.shapes.medium,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 6.dp)
                ) {
                    Column(modifier = Modifier.padding(14.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(
                                imageVector = Icons.Default.NotificationsActive,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.error
                            )
                            Spacer(modifier = Modifier.width(8.dp))
                            Text(
                                text = "إذن قراءة إشعارات واتساب والرسائل غير مفعل",
                                style = MaterialTheme.typography.titleSmall,
                                fontWeight = FontWeight.Bold,
                                color = MaterialTheme.colorScheme.onErrorContainer
                            )
                        }
                        Spacer(modifier = Modifier.height(6.dp))
                        Text(
                            text = "لكي يتمكن سند من قراءة رسائل واتساب والتنبيهات، يلزم تفعيل إذن الوصول للإشعارات.\n(لهواتف سامسونج: إذا ظهر 'إعداد مقيد'، اضغط الثلاث نقاط في معلومات التطبيق واختر 'السماح بالإعدادات المقيدة').",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onErrorContainer.copy(alpha = 0.9f)
                        )
                        Spacer(modifier = Modifier.height(10.dp))
                        Button(
                            onClick = onOpenNotificationSettings,
                            colors = ButtonDefaults.buttonColors(
                                containerColor = MaterialTheme.colorScheme.error
                            ),
                            shape = MaterialTheme.shapes.small
                        ) {
                            Text(
                                text = "تفعيل الوصول للإشعارات الآن",
                                color = MaterialTheme.colorScheme.onError,
                                style = MaterialTheme.typography.labelMedium
                            )
                        }
                    }
                }
            }

            // مساحة المحادثة أو شاشة الترحيب عند بدء الجلسة
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
            ) {
                if (chatItems.isEmpty()) {
                    // بطاقة ترحيبية مهنية عند فتح الجلسة
                    Column(
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(24.dp),
                        verticalArrangement = Arrangement.Center,
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        Surface(
                            shape = CircleShape,
                            color = MaterialTheme.colorScheme.primaryContainer,
                            modifier = Modifier.size(64.dp)
                        ) {
                            Box(contentAlignment = Alignment.Center) {
                                Icon(
                                    imageVector = Icons.Default.SmartToy,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.onPrimaryContainer,
                                    modifier = Modifier.size(32.dp)
                                )
                            }
                        }

                        Spacer(modifier = Modifier.height(16.dp))

                        Text(
                            text = "مرحباً بك، أنا سند",
                            style = MaterialTheme.typography.headlineSmall,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.onSurface
                        )

                        Spacer(modifier = Modifier.height(6.dp))

                        Text(
                            text = "سكرتيرك الشخصي الذكي المتصل بخادمك المنزلي. كيف أساعدك اليوم؟",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            textAlign = TextAlign.Center
                        )

                        Spacer(modifier = Modifier.height(24.dp))

                        // اقتراحات مهنية سريعة
                        val suggestions = listOf(
                            "ما هي آخر رسالة نصية SMS وصلتني؟",
                            "هل وصلتني رسائل جديدة في واتساب؟",
                            "لخص لي الرسائل والتنبيهات الأخيرة",
                            "أنشئ تذكير لاجتماع عمل غداً الساعة 10 صباحاً"
                        )

                        suggestions.forEach { prompt ->
                            SuggestionChip(
                                onClick = {
                                    chatItems.add(
                                        ChatItem.UserMessage(
                                            id = System.currentTimeMillis().toString(),
                                            text = prompt,
                                            ts = "الآن"
                                        )
                                    )
                                    wsClient.sendUserMessage(prompt)
                                },
                                label = { Text(prompt, style = MaterialTheme.typography.bodySmall) },
                                shape = MaterialTheme.shapes.small,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(vertical = 4.dp)
                            )
                        }
                    }
                } else {
                    LazyColumn(
                        state = listState,
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(horizontal = 16.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp)
                    ) {
                        item { Spacer(modifier = Modifier.height(8.dp)) }

                        items(chatItems) { item ->
                            when (item) {
                                is ChatItem.UserMessage -> {
                                    // في نسق RTL: محاذاة رسالة المستخدم نحو اليسار (End) مع زاوية مقوسة
                                    Box(
                                        modifier = Modifier.fillMaxWidth(),
                                        contentAlignment = Alignment.CenterEnd
                                    ) {
                                        Surface(
                                            shape = RoundedCornerShape(18.dp, 18.dp, 4.dp, 18.dp),
                                            color = MaterialTheme.colorScheme.primary,
                                            contentColor = MaterialTheme.colorScheme.onPrimary,
                                            modifier = Modifier.widthIn(max = 300.dp)
                                        ) {
                                            Text(
                                                text = item.text,
                                                style = MaterialTheme.typography.bodyMedium,
                                                textAlign = TextAlign.Start,
                                                modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp)
                                            )
                                        }
                                    }
                                }
                                is ChatItem.AssistantMessage -> {
                                    // محاذاة رد السكرتير نحو اليمين (Start)
                                    Box(
                                        modifier = Modifier.fillMaxWidth(),
                                        contentAlignment = Alignment.CenterStart
                                    ) {
                                        Surface(
                                            shape = RoundedCornerShape(18.dp, 18.dp, 18.dp, 4.dp),
                                            color = MaterialTheme.colorScheme.surfaceVariant,
                                            contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
                                            modifier = Modifier.widthIn(max = 320.dp)
                                        ) {
                                            Text(
                                                text = item.text,
                                                style = MaterialTheme.typography.bodyMedium,
                                                textAlign = TextAlign.Start,
                                                modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp)
                                            )
                                        }
                                    }
                                }
                                is ChatItem.HitlAction -> {
                                    HitlCard(
                                        actionRequest = item.request,
                                        currentStatus = item.status,
                                        onApprove = { actionId, version, argsHash, editedText ->
                                            if (item.request.requiresBiometric) {
                                                authenticateWithBiometrics {
                                                    wsClient.sendActionDecision(
                                                        actionId = actionId,
                                                        version = version,
                                                        argsHash = argsHash,
                                                        decision = "APPROVE",
                                                        editedText = editedText,
                                                        biometricOk = true
                                                    )
                                                }
                                            } else {
                                                wsClient.sendActionDecision(
                                                    actionId = actionId,
                                                    version = version,
                                                    argsHash = argsHash,
                                                    decision = "APPROVE",
                                                    editedText = editedText,
                                                    biometricOk = false
                                                )
                                            }
                                        },
                                        onReject = { actionId, version, argsHash ->
                                            wsClient.sendActionDecision(
                                                actionId = actionId,
                                                version = version,
                                                argsHash = argsHash,
                                                decision = "REJECT"
                                            )
                                        }
                                    )
                                }
                                is ChatItem.BriefingAttachment -> {
                                    BriefingCard(
                                        briefingId = item.briefingId,
                                        title = item.title,
                                        renderedText = item.renderedText,
                                        serverUrl = wsClient.serverUrl,
                                        token = wsClient.token,
                                        initialAcked = item.isAcked
                                    )
                                }
                                is ChatItem.FileAttachment -> {
                                    FileBubble(
                                        fileId = item.fileId,
                                        filename = item.filename,
                                        sizeBytes = item.sizeBytes,
                                        mimeType = item.mimeType,
                                        serverUrl = wsClient.serverUrl,
                                        token = wsClient.token
                                    )
                                }
                            }
                        }

                        item { Spacer(modifier = Modifier.height(8.dp)) }
                    }
                }
            }

            // شريط حالة التسجيل الصوتي أو التفريغ
            AnimatedVisibility(
                visible = isRecording,
                enter = fadeIn(),
                exit = fadeOut()
            ) {
                Surface(
                    color = StatusCritical.copy(alpha = 0.1f),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.Center
                    ) {
                        Box(
                            modifier = Modifier
                                .size(10.dp)
                                .clip(CircleShape)
                                .background(StatusCritical)
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = "جاري التسجيل الصوتي... اضغط على زر الإيقاف لإرسال الصوت وتفريغه",
                            style = MaterialTheme.typography.labelMedium,
                            fontWeight = FontWeight.Bold,
                            color = StatusCritical
                        )
                    }
                }
            }

            AnimatedVisibility(
                visible = isTranscribing,
                enter = fadeIn(),
                exit = fadeOut()
            ) {
                Surface(
                    color = MaterialTheme.colorScheme.primaryContainer,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.Center
                    ) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(16.dp),
                            strokeWidth = 2.dp,
                            color = MaterialTheme.colorScheme.onPrimaryContainer
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = "جاري تفريغ الصوت وتحويله لنص عربي عبر STT...",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onPrimaryContainer
                        )
                    }
                }
            }

            // شريط إشارة رفع المستندات قيد الانتظار
            if (isUploadingFile) {
                LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
            }

            // بطاقة المعاينة للمستند المرفق قبل الإرسال
            if (pendingAttachment != null) {
                val att = pendingAttachment!!
                Surface(
                    color = MaterialTheme.colorScheme.surfaceVariant,
                    shape = MaterialTheme.shapes.medium,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp, vertical = 4.dp)
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Icon(
                            imageVector = Icons.Default.Description,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.size(24.dp)
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = att.filename,
                                style = MaterialTheme.typography.labelMedium,
                                fontWeight = FontWeight.Bold,
                                maxLines = 1
                            )
                            val sizeKb = (att.sizeBytes / 1024).coerceAtLeast(1)
                            Text(
                                text = "$sizeKb KB • جاهز للإرسال مع الطلب",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        IconButton(onClick = { pendingAttachment = null }) {
                            Icon(
                                imageVector = Icons.Default.Close,
                                contentDescription = "إلغاء المرفق",
                                tint = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                }
            }

            // شريط إدخال الرسائل والمرفقات والأوامر الصوتية
            Surface(
                color = MaterialTheme.colorScheme.surface,
                tonalElevation = 3.dp,
                modifier = Modifier.fillMaxWidth()
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 10.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    // زر إرفاق المستندات
                    FilledTonalIconButton(
                        onClick = {
                            filePickerLauncher.launch("*/*")
                        },
                        colors = IconButtonDefaults.filledTonalIconButtonColors(
                            containerColor = MaterialTheme.colorScheme.surfaceVariant,
                            contentColor = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    ) {
                        Icon(
                            imageVector = Icons.Default.AttachFile,
                            contentDescription = "إرفاق مستند"
                        )
                    }

                    Spacer(modifier = Modifier.width(6.dp))

                    // زر التسجيل الصوتي STT
                    FilledTonalIconButton(
                        onClick = {
                            if (!isRecording) {
                                val permissionCheck = ContextCompat.checkSelfPermission(
                                    context,
                                    Manifest.permission.RECORD_AUDIO
                                )
                                if (permissionCheck == PackageManager.PERMISSION_GRANTED) {
                                    isRecording = audioManager.startRecording()
                                } else {
                                    permissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                                }
                            } else {
                                val audioFile = audioManager.stopRecording()
                                isRecording = false
                                if (audioFile != null && audioFile.exists()) {
                                    isTranscribing = true
                                    coroutineScope.launch {
                                        val res = audioManager.uploadAndTranscribe(
                                            serverUrl = wsClient.serverUrl,
                                            token = wsClient.token,
                                            audioFile = audioFile
                                        )
                                        isTranscribing = false
                                        res.onSuccess { transcribed ->
                                            if (transcribed.isNotBlank()) {
                                                chatItems.add(
                                                    ChatItem.UserMessage(
                                                        id = System.currentTimeMillis().toString(),
                                                        text = transcribed,
                                                        ts = "الآن"
                                                    )
                                                )
                                                wsClient.sendUserMessage(transcribed)
                                            }
                                        }.onFailure {
                                            Toast.makeText(context, "فشل تفريغ الصوت: ${it.message}", Toast.LENGTH_SHORT).show()
                                        }
                                    }
                                }
                            }
                        },
                        colors = IconButtonDefaults.filledTonalIconButtonColors(
                            containerColor = if (isRecording) StatusCritical.copy(alpha = 0.15f) else MaterialTheme.colorScheme.surfaceVariant,
                            contentColor = if (isRecording) StatusCritical else MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    ) {
                        Icon(
                            imageVector = if (isRecording) Icons.Default.Stop else Icons.Default.Mic,
                            contentDescription = if (isRecording) "إيقاف التسجيل" else "تسجيل صوتي"
                        )
                    }

                    Spacer(modifier = Modifier.width(6.dp))

                    OutlinedTextField(
                        value = inputText,
                        onValueChange = { inputText = it },
                        placeholder = {
                            Text(
                                "اطلب من سند أو اسأله شيئاً...",
                                style = MaterialTheme.typography.bodyMedium
                            )
                        },
                        modifier = Modifier.weight(1f),
                        maxLines = 4,
                        shape = MaterialTheme.shapes.extraLarge,
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedContainerColor = MaterialTheme.colorScheme.surface,
                            unfocusedContainerColor = MaterialTheme.colorScheme.surface
                        )
                    )

                    Spacer(modifier = Modifier.width(6.dp))

                    FilledIconButton(
                        onClick = { handleSendMessage() },
                        enabled = inputText.isNotBlank() || pendingAttachment != null,
                        shape = CircleShape
                    ) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.Send,
                            contentDescription = "إرسال"
                        )
                    }
                }
            }
        }
    }
}
