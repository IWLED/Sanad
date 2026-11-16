package app.secretary.sensor

import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.Telephony
import android.util.Log
import androidx.core.content.ContextCompat
import app.secretary.outbox.OutboxDbHelper
import app.secretary.outbox.OutboxSyncWorker
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

object SmsSyncManager {
    private const val TAG = "SmsSyncManager"

    suspend fun syncInboxSms(context: Context, limit: Int = 40): Result<Int> = withContext(Dispatchers.IO) {
        val hasPermission = ContextCompat.checkSelfPermission(
            context,
            android.Manifest.permission.READ_SMS
        ) == PackageManager.PERMISSION_GRANTED

        if (!hasPermission) {
            return@withContext Result.failure(SecurityException("إذن قراءة الرسائل النصية READ_SMS غير ممنوح"))
        }

        try {
            val contentResolver = context.contentResolver
            val uri: Uri = Telephony.Sms.Inbox.CONTENT_URI
            val projection = arrayOf(
                Telephony.Sms._ID,
                Telephony.Sms.ADDRESS,
                Telephony.Sms.BODY,
                Telephony.Sms.DATE
            )

            val cursor = contentResolver.query(
                uri,
                projection,
                null,
                null,
                "${Telephony.Sms.DATE} DESC LIMIT $limit"
            )

            var count = 0
            val db = OutboxDbHelper.getInstance(context)

            val df = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US).apply {
                timeZone = TimeZone.getTimeZone("UTC")
            }

            cursor?.use { c ->
                val idIdx = c.getColumnIndex(Telephony.Sms._ID)
                val addrIdx = c.getColumnIndex(Telephony.Sms.ADDRESS)
                val bodyIdx = c.getColumnIndex(Telephony.Sms.BODY)
                val dateIdx = c.getColumnIndex(Telephony.Sms.DATE)

                while (c.moveToNext()) {
                    val smsId = if (idIdx >= 0) c.getString(idIdx) else count.toString()
                    val address = if (addrIdx >= 0) c.getString(addrIdx) ?: "Unknown" else "Unknown"
                    val body = if (bodyIdx >= 0) c.getString(bodyIdx) ?: "" else ""
                    val timestamp = if (dateIdx >= 0) c.getLong(dateIdx) else System.currentTimeMillis()

                    if (body.isBlank()) continue

                    val occurredAt = df.format(Date(timestamp))
                    val externalId = "sms:$address:$smsId:$timestamp"

                    val payload = JSONObject().apply {
                        put("source", "sms")
                        put("external_id", externalId)
                        put("thread_key", "sms:$address")
                        put("app_package", "com.android.mms")
                        put("sender_name", address)
                        put("content", body)
                        put("reply_capable", false)
                        put("occurred_at", occurredAt)
                    }

                    val rowId = db.enqueueEvent("sms", externalId, payload)
                    if (rowId != -1L) {
                        count++
                    }
                }
            }

            if (count > 0) {
                Log.i(TAG, "Enqueued $count inbox SMS messages for sync")
                OutboxSyncWorker.enqueueImmediateSync(context)
            }

            Result.success(count)
        } catch (e: Exception) {
            Log.e(TAG, "Error syncing SMS inbox", e)
            Result.failure(e)
        }
    }
}
