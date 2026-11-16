package app.secretary.core.network

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

data class UploadedFileMeta(
    val fileId: String,
    val filename: String,
    val sizeBytes: Long,
    val mimeType: String,
    val extractedText: String?
)

object FileUploadManager {
    private const val TAG = "FileUploadManager"

    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .build()

    suspend fun uploadFile(
        context: Context,
        serverUrl: String,
        token: String,
        uri: Uri
    ): Result<UploadedFileMeta> = withContext(Dispatchers.IO) {
        try {
            val contentResolver = context.contentResolver
            var filename = "attachment"
            var size = 0L

            contentResolver.query(uri, null, null, null, null)?.use { cursor ->
                val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)
                if (cursor.moveToFirst()) {
                    if (nameIndex >= 0) filename = cursor.getString(nameIndex) ?: filename
                    if (sizeIndex >= 0) size = cursor.getLong(sizeIndex)
                }
            }

            val mimeType = contentResolver.getType(uri) ?: "application/octet-stream"
            val inputStream = contentResolver.openInputStream(uri)
                ?: return@withContext Result.failure(IllegalStateException("تعذر فتح الملف المختار"))

            val bytes = inputStream.use { it.readBytes() }
            val requestBody = bytes.toRequestBody(mimeType.toMediaTypeOrNull())

            val multipartBody = MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart("file", filename, requestBody)
                .build()

            val request = Request.Builder()
                .url("${serverUrl.trimEnd('/')}/v1/files/upload")
                .header("Authorization", "Bearer $token")
                .post(multipartBody)
                .build()

            val response = httpClient.newCall(request).execute()
            val bodyString = response.body?.string() ?: ""

            if (!response.isSuccessful) {
                Log.e(TAG, "File upload failed with code ${response.code}: $bodyString")
                return@withContext Result.failure(Exception("فشل رفع الملف (${response.code})"))
            }

            val json = JSONObject(bodyString)
            val meta = UploadedFileMeta(
                fileId = json.getString("file_id"),
                filename = json.getString("filename"),
                sizeBytes = json.getLong("size_bytes"),
                mimeType = json.getString("mime_type"),
                extractedText = if (json.has("extracted_text") && !json.isNull("extracted_text")) json.getString("extracted_text") else null
            )

            Result.success(meta)
        } catch (e: Exception) {
            Log.e(TAG, "Exception during file upload", e)
            Result.failure(e)
        }
    }
}
