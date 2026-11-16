package app.secretary.ui

import android.Manifest
import android.content.pm.PackageManager
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import app.secretary.core.audio.AudioRecordManager
import app.secretary.core.network.ConnectionStatus
import app.secretary.core.network.SanadWebSocketClient
import app.secretary.core.network.ServerWsEvent
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch

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
    modifier: Modifier = Modifier
) {
    val context = LocalContext.current
    val coroutineScope = rememberCoroutineScope()
    val connectionStatus by wsClient.connectionStatus.collectAsState()
    var inputText by remember { mutableStateOf("") }
    val chatItems = remember { mutableStateListOf<ChatItem>() }

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
                    val fileRegex = Regex("""/v1/files/(fil_[a-f0-9]+)/download""")
                    val match = fileRegex.find(event.text)
                    if (match != null) {
                        val fileId = match.groupValues[1]
                        val filename = when {
                            event.text.contains(".docx") -> "$fileId.docx"
                            event.text.contains(".xlsx") -> "$fileId.xlsx"
                            event.text.contains(".pptx") -> "$fileId.pptx"
                            else -> "$fileId.bin"
                        }
                        val mime = when {
                            filename.endsWith(".docx") -> "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                            filename.endsWith(".xlsx") -> "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                            filename.endsWith(".pptx") -> "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                            else -> "application/octet-stream"
                        }
                        chatItems.add(
                            ChatItem.FileAttachment(
                                fileId = fileId,
                                filename = filename,
                                sizeBytes = 15000L,
                                mimeType = mime
                            )
                        )
                    }
                }
                is ServerWsEvent.BriefingReady -> {
                    chatItems.add(
                        ChatItem.BriefingAttachment(
                            briefingId = event.briefingId,
                            title = event.title,
                            renderedText = event.renderedText,
                            isAcked = false
                        )
                    )
                }
                is ServerWsEvent.ReminderAlert -> {
                    chatItems.add(
                        ChatItem.AssistantMessage(
                            id = System.currentTimeMillis().toString(),
                            text = "🔔 تذكير: ${event.title}\n${event.notes ?: ""}",
                            ts = "الآن"
                        )
                    )
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
                is ServerWsEvent.Error -> {
                    Toast.makeText(context, "خطأ: ${event.message}", Toast.LENGTH_SHORT).show()
                }
                else -> {}
            }
        }
    }

    // دالة طلب البصمة الحيوية عند اعتماد إجراءات المستوى الثالث T3 (R-12, D-8)
    fun authenticateWithBiometrics(onSuccess: () -> Unit) {
        val activity = context as? FragmentActivity
        if (activity == null) {
            Toast.makeText(context, "تعذر تشغيل التحقق بالبصمة", Toast.LENGTH_SHORT).show()
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
                    Toast.makeText(context, "فشل التحقق: $errString", Toast.LENGTH_SHORT).show()
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

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("سند — السكرتير الشخصي", fontWeight = FontWeight.Bold)
                        Spacer(modifier = Modifier.width(8.dp))
                        val statusDotColor = when (connectionStatus) {
                            ConnectionStatus.CONNECTED -> Color(0xFF2E7D32)
                            ConnectionStatus.CONNECTING -> Color(0xFFF57C00)
                            ConnectionStatus.DISCONNECTED -> Color(0xFFC62828)
                        }
                        Box(
                            modifier = Modifier
                                .size(10.dp)
                                .clip(CircleShape)
                                .background(statusDotColor)
                        )
                    }
                },
                navigationIcon = {
                    TextButton(onClick = onBack) {
                        Text("خروج")
                    }
                }
            )
        },
        modifier = modifier
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
        ) {
            // 1. قائمة الرسائل وبطاقات HITL والإيجاز والملفات
            LazyColumn(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp),
                reverseLayout = false
            ) {
                items(chatItems) { item ->
                    when (item) {
                        is ChatItem.UserMessage -> {
                            Box(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(vertical = 4.dp),
                                contentAlignment = Alignment.CenterEnd
                            ) {
                                Box(
                                    modifier = Modifier
                                        .clip(RoundedCornerShape(16.dp, 16.dp, 2.dp, 16.dp))
                                        .background(MaterialTheme.colorScheme.primary)
                                        .padding(horizontal = 14.dp, vertical = 10.dp)
                                ) {
                                    Text(
                                        text = item.text,
                                        color = MaterialTheme.colorScheme.onPrimary,
                                        fontSize = 15.sp
                                    )
                                }
                            }
                        }
                        is ChatItem.AssistantMessage -> {
                            Box(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(vertical = 4.dp),
                                contentAlignment = Alignment.CenterStart
                            ) {
                                Box(
                                    modifier = Modifier
                                        .clip(RoundedCornerShape(16.dp, 16.dp, 16.dp, 2.dp))
                                        .background(MaterialTheme.colorScheme.secondaryContainer)
                                        .padding(horizontal = 14.dp, vertical = 10.dp)
                                ) {
                                    Text(
                                        text = item.text,
                                        color = MaterialTheme.colorScheme.onSecondaryContainer,
                                        fontSize = 15.sp
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
            }

            // شريط حالة التسجيل أو التفريغ الصوتي
            if (isRecording) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(Color(0xFFD32F2F).copy(alpha = 0.15f))
                        .padding(vertical = 8.dp),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = "🔴 جاري التسجيل الصوتي... انقر على زر الميكروفون للإرسال والتفريغ",
                        color = Color(0xFFD32F2F),
                        fontSize = 12.sp,
                        fontWeight = FontWeight.Bold
                    )
                }
            } else if (isTranscribing) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(MaterialTheme.colorScheme.primaryContainer)
                        .padding(vertical = 8.dp),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = "⏳ جاري تفريغ الصوت وتحويله لنص عربي عبر STT...",
                        color = MaterialTheme.colorScheme.onPrimaryContainer,
                        fontSize = 12.sp
                    )
                }
            }

            // 2. شريط إدخال الرسالة والإرسال وزر الميكروفون الصوتي
            HorizontalDivider()
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                // زر التسجيل الصوتي STT (Section 11.4)
                IconButton(
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
                                                    text = "🎤 $transcribed",
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
                    modifier = Modifier.size(44.dp)
                ) {
                    Text(
                        text = if (isRecording) "⏹" else "🎙",
                        fontSize = 22.sp
                    )
                }

                Spacer(modifier = Modifier.width(4.dp))

                OutlinedTextField(
                    value = inputText,
                    onValueChange = { inputText = it },
                    placeholder = { Text("اكتب رسالتك لسند...") },
                    modifier = Modifier.weight(1f),
                    maxLines = 4,
                    shape = RoundedCornerShape(24.dp)
                )

                Spacer(modifier = Modifier.width(8.dp))

                Button(
                    onClick = {
                        val text = inputText.trim()
                        if (text.isNotEmpty()) {
                            chatItems.add(
                                ChatItem.UserMessage(
                                    id = System.currentTimeMillis().toString(),
                                    text = text,
                                    ts = "الآن"
                                )
                            )
                            wsClient.sendUserMessage(text)
                            inputText = ""
                        }
                    },
                    shape = CircleShape,
                    modifier = Modifier.size(48.dp),
                    contentPadding = PaddingValues(0.dp)
                ) {
                    Text("↑", fontSize = 20.sp, fontWeight = FontWeight.Bold)
                }
            }
        }
    }
}
