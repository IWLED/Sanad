package app.secretary.core.audio

import android.content.Context
import android.media.MediaRecorder
import android.os.Build
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * مدير تسجيل الصوت ورفعه للتفريغ (STT Client) (Section 11.4).
 * الحد الأقصى للتسجيل 120 ثانية، ويتم حذف الملف فور الانتهاء دون إبقاء أثر.
 */
class AudioRecordManager(private val context: Context) {

    private var recorder: MediaRecorder? = null
    private var currentAudioFile: File? = null
    private var isRecording = false

    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .build()

    fun isCurrentlyRecording(): Boolean = isRecording

    fun startRecording(): Boolean {
        if (isRecording) return false

        return try {
            val cacheDir = context.cacheDir
            val audioFile = File(cacheDir, "voice_note_${System.currentTimeMillis()}.m4a")
            currentAudioFile = audioFile

            val mr = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                MediaRecorder(context)
            } else {
                @Suppress("DEPRECATION")
                MediaRecorder()
            }

            mr.apply {
                setAudioSource(MediaRecorder.AudioSource.MIC)
                setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
                setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
                setAudioEncodingBitRate(128000)
                setAudioSamplingRate(44100)
                setOutputFile(audioFile.absolutePath)
                setMaxDuration(120_000) // 120 ثانية كحد أقصى (Section 11.4)
                prepare()
                start()
            }

            recorder = mr
            isRecording = true
            Log.i("AudioRecordManager", "Started voice recording: ${audioFile.name}")
            true
        } catch (e: Exception) {
            Log.e("AudioRecordManager", "Failed to start recording", e)
            cleanup()
            false
        }
    }

    fun stopRecording(): File? {
        if (!isRecording) return null

        return try {
            recorder?.apply {
                stop()
                release()
            }
            recorder = null
            isRecording = false
            currentAudioFile
        } catch (e: Exception) {
            Log.e("AudioRecordManager", "Error stopping recorder", e)
            cleanup()
            null
        }
    }

    fun cancelRecording() {
        try {
            recorder?.apply {
                stop()
                release()
            }
        } catch (_: Exception) {}
        cleanup()
    }

    private fun cleanup() {
        recorder = null
        isRecording = false
        currentAudioFile?.let {
            if (it.exists()) it.delete()
        }
        currentAudioFile = null
    }

    /**
     * رفع الملف الصوتي للتفريغ النصي عبر POST /v1/audio/transcribe
     * وحذف الملف فور الانتهاء لضمان R-08.
     */
    suspend fun uploadAndTranscribe(
        serverUrl: String,
        token: String,
        audioFile: File,
        lang: String = "ar"
    ): Result<String> = withContext(Dispatchers.IO) {
        try {
            val url = "${serverUrl.trimEnd('/')}/v1/audio/transcribe"
            val fileBody = audioFile.asRequestBody("audio/m4a".toMediaType())

            val requestBody = MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart("lang", lang)
                .addFormDataPart("file", audioFile.name, fileBody)
                .build()

            val request = Request.Builder()
                .url(url)
                .addHeader("Authorization", "Bearer $token")
                .post(requestBody)
                .build()

            val response = httpClient.newCall(request).execute()
            val responseBody = response.body?.string() ?: ""

            if (response.isSuccessful) {
                val json = JSONObject(responseBody)
                val text = json.optString("text", "").trim()
                Result.success(text)
            } else {
                Result.failure(Exception("HTTP error ${response.code}: $responseBody"))
            }
        } catch (e: Exception) {
            Log.e("AudioRecordManager", "Transcription upload failed", e)
            Result.failure(e)
        } finally {
            // حذف الملف الصوتي المؤقت فور الانتهاء R-08
            if (audioFile.exists()) {
                audioFile.delete()
            }
        }
    }
}
