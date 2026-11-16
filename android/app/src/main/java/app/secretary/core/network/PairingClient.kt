package app.secretary.core.network

import android.os.Build
import app.secretary.core.security.AndroidKeystoreManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException
import java.time.Instant
import java.util.UUID

/**
 * عميل شبكي لتنفيذ عملية الاقتران وتجديد الجلسة وتوقيع الطلبات (Section 8.1).
 */
class PairingClient(
    private val serverBaseUrl: String,
    private val keystoreManager: AndroidKeystoreManager,
    private val httpClient: OkHttpClient = OkHttpClient()
) {
    data class AuthSession(
        val deviceId: String,
        val accessToken: String,
        val refreshToken: String,
        val expiresInSeconds: Int
    )

    private val jsonMediaType = "application/json; charset=utf-8".toMediaType()

    /**
     * إرسال طلب الاقتران الأولي بالخادم باستخدام الرمز الممسوح والمفتاح العام.
     */
    suspend fun pair(
        code: String,
        deviceName: String = "${Build.MANUFACTURER} ${Build.MODEL}",
        fcmToken: String? = null
    ): Result<AuthSession> = withContext(Dispatchers.IO) {
        try {
            val pubkeyPem = keystoreManager.getPublicKeyPem()
            val jsonPayload = JSONObject().apply {
                put("code", code)
                put("device_name", deviceName)
                put("pubkey_pem", pubkeyPem)
                if (fcmToken != null) put("fcm_token", fcmToken)
                put("android_sdk", Build.VERSION.SDK_INT)
                put("app_version", "1.0.0")
            }

            val request = Request.Builder()
                .url("$serverBaseUrl/v1/pair")
                .post(jsonPayload.toString().toRequestBody(jsonMediaType))
                .build()

            val response = httpClient.newCall(request).execute()
            val bodyStr = response.body?.string() ?: ""

            if (!response.isSuccessful) {
                return@withContext Result.failure(
                    IOException("فشل الاقتران (${response.code}): $bodyStr")
                )
            }

            val resJson = JSONObject(bodyStr)
            val session = AuthSession(
                deviceId = resJson.getString("device_id"),
                accessToken = resJson.getString("access_token"),
                refreshToken = resJson.getString("refresh_token"),
                expiresInSeconds = resJson.getInt("expires_in")
            )
            Result.success(session)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * تجديد رمز الوصول (Refresh) مع توقيع الـ Nonce والوقت عبر الـ Keystore.
     */
    suspend fun refreshTokens(
        deviceId: String,
        currentRefreshToken: String
    ): Result<AuthSession> = withContext(Dispatchers.IO) {
        try {
            val ts = Instant.now().toString()
            val nonce = UUID.randomUUID().toString().replace("-", "")

            // توقيع الرسالة device_id|ts|nonce
            val messageToSign = "$deviceId|$ts|$nonce".toByteArray(Charsets.UTF_8)
            val signature = keystoreManager.sign(messageToSign)

            val jsonPayload = JSONObject().apply {
                put("device_id", deviceId)
                put("refresh_token", currentRefreshToken)
                put("ts", ts)
                put("nonce", nonce)
                put("signature", signature)
            }

            val request = Request.Builder()
                .url("$serverBaseUrl/v1/auth/refresh")
                .post(jsonPayload.toString().toRequestBody(jsonMediaType))
                .build()

            val response = httpClient.newCall(request).execute()
            val bodyStr = response.body?.string() ?: ""

            if (!response.isSuccessful) {
                return@withContext Result.failure(
                    IOException("فشل تجديد الجلسة (${response.code}): $bodyStr")
                )
            }

            val resJson = JSONObject(bodyStr)
            val session = AuthSession(
                deviceId = deviceId,
                accessToken = resJson.getString("access_token"),
                refreshToken = resJson.getString("refresh_token"),
                expiresInSeconds = resJson.getInt("expires_in")
            )
            Result.success(session)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}
