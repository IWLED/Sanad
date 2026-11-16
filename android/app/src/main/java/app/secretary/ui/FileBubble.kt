package app.secretary.ui

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.OpenInNew
import androidx.compose.material.icons.filled.Slideshow
import androidx.compose.material.icons.filled.TableChart
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
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
 * بتصميم Material Design 3 تنفيذي موحد وواضح.
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

    val (icon, typeLabel) = remember(filename, mimeType) {
        when {
            filename.endsWith(".docx") || mimeType.contains("word") -> Pair(Icons.Default.Description, "مستند Word")
            filename.endsWith(".xlsx") || mimeType.contains("sheet") -> Pair(Icons.Default.TableChart, "جدول بيانات Excel")
            filename.endsWith(".pptx") || mimeType.contains("presentation") -> Pair(Icons.Default.Slideshow, "عرض PowerPoint")
            else -> Pair(Icons.Default.Folder, "مستند")
        }
    }

    val formattedSize = remember(sizeBytes) {
        when {
            sizeBytes < 1024 -> "$sizeBytes B"
            sizeBytes < 1024 * 1024 -> "${sizeBytes / 1024} KB"
            else -> "${sizeBytes / (1024 * 1024)} MB"
        }
    }

    OutlinedCard(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp),
        shape = MaterialTheme.shapes.medium,
        colors = CardDefaults.outlinedCardColors(
            containerColor = MaterialTheme.colorScheme.surface
        )
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.weight(1f)
            ) {
                Surface(
                    shape = MaterialTheme.shapes.small,
                    color = MaterialTheme.colorScheme.primaryContainer,
                    modifier = Modifier.size(44.dp)
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Icon(
                            imageVector = icon,
                            contentDescription = typeLabel,
                            tint = MaterialTheme.colorScheme.onPrimaryContainer,
                            modifier = Modifier.size(24.dp)
                        )
                    }
                }

                Spacer(modifier = Modifier.width(12.dp))

                Column {
                    Text(
                        text = filename,
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.SemiBold,
                        color = MaterialTheme.colorScheme.onSurface,
                        maxLines = 1
                    )
                    Spacer(modifier = Modifier.height(2.dp))
                    Text(
                        text = "$typeLabel • $formattedSize",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }

            Spacer(modifier = Modifier.width(12.dp))

            FilledTonalButton(
                onClick = {
                    if (isDownloading) return@FilledTonalButton
                    isDownloading = true
                    coroutineScope.launch {
                        val downloadedFile = downloadFile(context, serverUrl, token, fileId, filename)
                        isDownloading = false
                        if (downloadedFile != null) {
                            openFile(context, downloadedFile, mimeType)
                        } else {
                            Toast.makeText(context, "فشل تنزيل الملف من الخادم", Toast.LENGTH_SHORT).show()
                        }
                    }
                },
                enabled = !isDownloading,
                shape = MaterialTheme.shapes.small,
                contentPadding = PaddingValues(horizontal = 14.dp, vertical = 8.dp)
            ) {
                if (isDownloading) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(16.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onSecondaryContainer
                    )
                    Spacer(modifier = Modifier.width(6.dp))
                    Text("جاري التحميل", style = MaterialTheme.typography.labelMedium)
                } else {
                    Icon(
                        imageVector = Icons.Default.OpenInNew,
                        contentDescription = "فتح الملف",
                        modifier = Modifier.size(16.dp)
                    )
                    Spacer(modifier = Modifier.width(6.dp))
                    Text("فتح الملف", style = MaterialTheme.typography.labelMedium)
                }
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

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) return@withContext null
            val body = response.body ?: return@withContext null

            val exportsDir = File(context.cacheDir, "sanad_exports").apply { mkdirs() }
            val destFile = File(exportsDir, filename)

            FileOutputStream(destFile).use { output ->
                body.byteStream().copyTo(output)
            }
            destFile
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
    } catch (_: Exception) {
        Toast.makeText(context, "لا يوجد تطبيق مثبت لفتح هذا النوع من الملفات", Toast.LENGTH_LONG).show()
    }
}
