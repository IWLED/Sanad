package app.secretary.ui

import android.content.Context
import android.speech.tts.TextToSpeech
import android.widget.Toast
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.EventNote
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.VolumeUp
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import app.secretary.ui.theme.StatusSuccess
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.Locale

/**
 * بطاقة عرض الإيجاز الذكي اليومي (Briefing Card - Section 11.1).
 * مصممة وفق معايير Material 3 بأسلوب هادئ وأنيق يدعم القراءة الصوتية والتأكيد.
 */
@Composable
fun BriefingCard(
    briefingId: String,
    title: String,
    renderedText: String,
    serverUrl: String,
    token: String,
    initialAcked: Boolean = false,
    modifier: Modifier = Modifier
) {
    val context = LocalContext.current
    val coroutineScope = rememberCoroutineScope()
    var isAcked by remember(briefingId) { mutableStateOf(initialAcked) }
    var isSpeaking by remember { mutableStateOf(false) }
    var isSubmittingAck by remember { mutableStateOf(false) }
    var ttsInstance by remember { mutableStateOf<TextToSpeech?>(null) }

    // تهيئة محرك تحويل النص إلى كلام محلياً (Android TTS)
    DisposableEffect(Unit) {
        var tts: TextToSpeech? = null
        tts = TextToSpeech(context) { status ->
            if (status == TextToSpeech.SUCCESS) {
                tts?.language = Locale.forLanguageTag("ar")
                ttsInstance = tts
            }
        }
        onDispose {
            tts?.stop()
            tts?.shutdown()
        }
    }

    ElevatedCard(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = 6.dp),
        shape = MaterialTheme.shapes.large,
        colors = CardDefaults.elevatedCardColors(
            containerColor = MaterialTheme.colorScheme.surface
        ),
        elevation = CardDefaults.elevatedCardElevation(defaultElevation = 1.dp)
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(18.dp)
        ) {
            // الرأس: أيقونة الإيجاز والعنوان وحالة الاطلاع
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.weight(1f)
                ) {
                    Surface(
                        shape = MaterialTheme.shapes.small,
                        color = MaterialTheme.colorScheme.tertiaryContainer,
                        modifier = Modifier.size(36.dp)
                    ) {
                        Box(contentAlignment = Alignment.Center) {
                            Icon(
                                imageVector = Icons.Default.EventNote,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.onTertiaryContainer,
                                modifier = Modifier.size(20.dp)
                            )
                        }
                    }

                    Spacer(modifier = Modifier.width(10.dp))

                    Text(
                        text = title,
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.onSurface
                    )
                }

                if (isAcked) {
                    SuggestionChip(
                        onClick = {},
                        label = {
                            Text(
                                "تم الاطلاع",
                                style = MaterialTheme.typography.labelSmall,
                                fontWeight = FontWeight.Bold,
                                color = StatusSuccess
                            )
                        },
                        icon = {
                            Icon(
                                imageVector = Icons.Default.Check,
                                contentDescription = null,
                                tint = StatusSuccess,
                                modifier = Modifier.size(14.dp)
                            )
                        },
                        colors = SuggestionChipDefaults.suggestionChipColors(
                            containerColor = StatusSuccess.copy(alpha = 0.1f)
                        ),
                        border = null,
                        shape = MaterialTheme.shapes.extraSmall
                    )
                }
            }

            Spacer(modifier = Modifier.height(14.dp))

            // نص ملخص الإيجاز
            Surface(
                shape = MaterialTheme.shapes.medium,
                color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(
                    text = renderedText,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(14.dp)
                )
            }

            Spacer(modifier = Modifier.height(16.dp))

            // شريط الإجراءات: استماع صوتي محلي + تأكيد الاطلاع
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End,
                verticalAlignment = Alignment.CenterVertically
            ) {
                FilledTonalButton(
                    onClick = {
                        val tts = ttsInstance
                        if (tts != null) {
                            if (isSpeaking) {
                                tts.stop()
                                isSpeaking = false
                            } else {
                                tts.speak(renderedText, TextToSpeech.QUEUE_FLUSH, null, "briefing_tts")
                                isSpeaking = true
                            }
                        } else {
                            Toast.makeText(context, "محرك النطق الصوتي غير جاهز", Toast.LENGTH_SHORT).show()
                        }
                    },
                    shape = MaterialTheme.shapes.small
                ) {
                    Icon(
                        imageVector = if (isSpeaking) Icons.Default.Stop else Icons.Default.VolumeUp,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp)
                    )
                    Spacer(modifier = Modifier.width(6.dp))
                    Text(
                        if (isSpeaking) "إيقاف الصوت" else "استماع صوتي",
                        style = MaterialTheme.typography.labelMedium
                    )
                }

                if (!isAcked) {
                    Spacer(modifier = Modifier.width(8.dp))
                    Button(
                        onClick = {
                            if (isSubmittingAck) return@Button
                            isSubmittingAck = true
                            coroutineScope.launch {
                                val success = sendBriefingAck(serverUrl, token, briefingId)
                                isSubmittingAck = false
                                if (success) {
                                    isAcked = true
                                    Toast.makeText(context, "تم تأكيد الاطلاع", Toast.LENGTH_SHORT).show()
                                } else {
                                    Toast.makeText(context, "تعذر حفظ التأكيد على الخادم", Toast.LENGTH_SHORT).show()
                                }
                            }
                        },
                        enabled = !isSubmittingAck,
                        shape = MaterialTheme.shapes.small
                    ) {
                        if (isSubmittingAck) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(16.dp),
                                strokeWidth = 2.dp,
                                color = MaterialTheme.colorScheme.onPrimary
                            )
                        } else {
                            Icon(
                                imageVector = Icons.Default.Check,
                                contentDescription = null,
                                modifier = Modifier.size(18.dp)
                            )
                            Spacer(modifier = Modifier.width(6.dp))
                            Text("تأكيد الاطلاع", style = MaterialTheme.typography.labelMedium)
                        }
                    }
                }
            }
        }
    }
}

private suspend fun sendBriefingAck(
    serverUrl: String,
    token: String,
    briefingId: String
): Boolean = withContext(Dispatchers.IO) {
    try {
        val client = OkHttpClient()
        val url = "${serverUrl.trimEnd('/')}/v1/briefings/$briefingId/ack"
        val emptyBody = "{}".toRequestBody("application/json".toMediaType())
        val request = Request.Builder()
            .url(url)
            .addHeader("Authorization", "Bearer $token")
            .post(emptyBody)
            .build()

        client.newCall(request).execute().use { response ->
            response.isSuccessful
        }
    } catch (_: Exception) {
        false
    }
}
