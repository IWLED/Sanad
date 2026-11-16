package app.secretary.ui

import android.content.Context
import android.content.Intent
import android.net.Uri
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
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.FileOutputStream

/**
 * فقاعة عرض وتنزيل المستندات المولدة برمجياً (Section 11.8 - FileBubble).
 * تدعم تنزيل ملفات Word و Excel و PowerPoint وفتحها عبر FileProvider.
 */
@Composable
fun FileBubble(
    fileId: String,
    filename: String,
    sizeBytes: Long,
    mimeType: String,
    serverUrl: String,
    token: String,
    modifier: Modifier = Modifier
) {
    val context = LocalContext.current
    val coroutineScope = rememberCoroutineScope()
    var isDownloading by remember { mutableStateOf(false) }

    val iconText = when {
        filename.endsWith(".docx") || mimeType.contains("word") -> "📄 Word"
        filename.endsWith(".xlsx") || mimeType.contains("sheet") -> "📊 Excel"
        filename.endsWith(".pptx") || mimeType.contains("presentation") -> "📑 PowerPoint"
        else -> "📁 مستند"
    }

    val formattedSize = remember(sizeBytes) {
        if (sizeBytes < 1024) "$sizeBytes B"
        else if (sizeBytes < 1024 * 1024) "${sizeBytes / 1024} KB"
        else "${sizeBytes / (1024 * 1024)} MB"
    }

    Card(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp),
        shape = RoundedCornerShape(14.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant
        ),
        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.weight(1f)
            ) {
                Box(
                    modifier = Modifier
                        .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.15f), RoundedCornerShape(8.dp))
                        .padding(horizontal = 8.dp, vertical = 6.dp)
                ) {
                    Text(
                        text = iconText,
                        fontSize = 12.sp,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.primary
                    )
                }

                Spacer(modifier = Modifier.width(10.dp))

                Column {
                    Text(
                        text = filename,
                        fontSize = 14.sp,
                        fontWeight = FontWeight.SemiBold,
                        maxLines = 1,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Text(
                        text = formattedSize,
                        fontSize = 11.sp,
                        color = Color.Gray
                    )
                }
            }

            Spacer(modifier = Modifier.width(8.dp))

            Button(
                onClick = {
                    if (isDownloading) return@Button
                    isDownloading = true
                    coroutineScope.launch {
                        val downloadedFile = downloadFile(context, serverUrl, token, fileId, filename)
                        isDownloading = false
                        if (downloadedFile != null) {
                            openFile(context, downloadedFile, mimeType)
                        } else {
                            Toast.makeText(context, "فشل تنزيل الملف", Toast.LENGTH_SHORT).show()
                        }
                    }
                },
                enabled = !isDownloading,
                shape = RoundedCornerShape(10.dp)
            ) {
                Text(if (isDownloading) "جاري التحميل..." else "فتح الملف")
            }
        }
    }
}

private suspend fun downloadFile(
    context: Context,
    serverUrl: String,
    token: String,
    fileId: String,
    filename: String
): File? = withContext(Dispatchers.IO) {
    try {
        val client = OkHttpClient()
        val url = "${serverUrl.trimEnd('/')}/v1/files/$fileId/download"
        val request = Request.Builder()
            .url(url)
            .addHeader("Authorization", "Bearer $token")
            .get()
            .build()

        val response = client.newCall(request).execute()
        if (response.isSuccessful) {
            val bytes = response.body?.bytes() ?: return@withContext null
            val destDir = File(context.cacheDir, "downloads")
            if (!destDir.exists()) destDir.mkdirs()
            val destFile = File(destDir, filename)
            FileOutputStream(destFile).use { it.write(bytes) }
            destFile
        } else {
            null
        }
    } catch (_: Exception) {
        null
    }
}

private fun openFile(context: Context, file: File, mimeType: String) {
    try {
        val uri: Uri = FileProvider.getUriForFile(
            context,
            "${context.packageName}.fileprovider",
            file
        )
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, mimeType)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(intent)
    } catch (e: Exception) {
        Toast.makeText(context, "لا يوجد تطبيق مناسب لفتح هذا الملف", Toast.LENGTH_SHORT).show()
    }
}
