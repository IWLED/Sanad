package app.secretary.ui

import android.content.Context
import android.speech.tts.TextToSpeech
import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
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
 * تدعم القراءة الصوتية المحلية (TTS) وتأكيد الاطلاع (Ack).
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
    var ttsInstance by remember { mutableStateOf<TextToSpeech?>(null) }

    // تهيئة محرك تحويل النص إلى كلام محلياً (Android TTS)
    DisposableEffect(Unit) {
        var tts: TextToSpeech? = null
        tts = TextToSpeech(context) { status ->
            if (status == TextToSpeech.SUCCESS) {
                tts?.language = Locale("ar")
                ttsInstance = tts
            }
        }
        onDispose {
            tts?.stop()
            tts?.shutdown()
        }
    }

    Card(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = 8.dp),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.primaryContainer
        ),
        elevation = CardDefaults.cardElevation(defaultElevation = 3.dp)
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp)
        ) {
            // الرأس: عنوان الإيجاز وحالة الاطلاع
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = title,
                    fontWeight = FontWeight.Bold,
                    fontSize = 17.sp,
                    color = MaterialTheme.colorScheme.onPrimaryContainer
                )

                if (isAcked) {
                    Box(
                        modifier = Modifier
                            .background(Color(0xFF2E7D32), RoundedCornerShape(8.dp))
                            .padding(horizontal = 8.dp, vertical = 4.dp)
                    ) {
                        Text(
                            text = "✓ تم الاطلاع",
                            color = Color.White,
                            fontSize = 11.sp,
                            fontWeight = FontWeight.Bold
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(12.dp))

            // نص الملخص
            Text(
                text = renderedText,
                fontSize = 14.sp,
                lineHeight = 22.sp,
                color = MaterialTheme.colorScheme.onPrimaryContainer
            )

            Spacer(modifier = Modifier.height(16.dp))

            // أزرار الإجراءات: الاستماع الصوتي + تأكيد الاطلاع
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End,
                verticalAlignment = Alignment.CenterVertically
            ) {
                // زر الاستماع عبر TTS المحلي (Section 11.4)
                OutlinedButton(
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
                    shape = RoundedCornerShape(10.dp)
                ) {
                    Text(if (isSpeaking) "⏹ إيقاف" else "🔊 استماع")
                }

                if (!isAcked) {
                    Spacer(modifier = Modifier.width(8.dp))
                    Button(
                        onClick = {
                            coroutineScope.launch {
                                val success = sendBriefingAck(serverUrl, token, briefingId)
                                if (success) {
                                    isAcked = true
                                    Toast.makeText(context, "تم تأكيد قراءة الإيجاز", Toast.LENGTH_SHORT).show()
                                } else {
                                    Toast.makeText(context, "تعذر تأكيد القراءة", Toast.LENGTH_SHORT).show()
                                }
                            }
                        },
                        shape = RoundedCornerShape(10.dp),
                        colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary)
                    ) {
                        Text("تم الاطلاع")
                    }
                }
            }
        }
    }
}

/**
 * إرسال تأكيد قراءة الإيجاز إلى الخادم POST /v1/briefings/{id}/ack (Section 11.1).
 */
private suspend fun sendBriefingAck(serverUrl: String, token: String, briefingId: String): Boolean =
    withContext(Dispatchers.IO) {
        try {
            val client = OkHttpClient()
            val url = "${serverUrl.trimEnd('/')}/v1/briefings/$briefingId/ack"
            val request = Request.Builder()
                .url(url)
                .addHeader("Authorization", "Bearer $token")
                .post("{}".toRequestBody("application/json".toMediaType()))
                .build()

            val response = client.newCall(request).execute()
            response.isSuccessful
        } catch (_: Exception) {
            false
        }
    }
