package app.secretary.sensor

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony
import android.telephony.TelephonyManager
import android.util.Log
import app.secretary.outbox.OutboxDbHelper
import app.secretary.outbox.OutboxSyncWorker
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

class TelephonyReceiver : BroadcastReceiver() {

    companion object {
        private const val TAG = "TelephonyReceiver"
        private var lastState = TelephonyManager.EXTRA_STATE_IDLE
        private var ringingNumber: String? = null
        private var isIncoming = false
    }

    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.action ?: return

        if (action == TelephonyManager.ACTION_PHONE_STATE_CHANGED) {
            handlePhoneState(context, intent)
        } else if (action == Telephony.Sms.Intents.SMS_RECEIVED_ACTION) {
            handleSms(context, intent)
        }
    }

    private fun handlePhoneState(context: Context, intent: Intent) {
        val state = intent.getStringExtra(TelephonyManager.EXTRA_STATE) ?: return
        val number = intent.getStringExtra(TelephonyManager.EXTRA_INCOMING_NUMBER)

        if (number != null && number.isNotEmpty()) {
            ringingNumber = number
        }

        if (state == TelephonyManager.EXTRA_STATE_RINGING) {
            isIncoming = true
            lastState = TelephonyManager.EXTRA_STATE_RINGING
        } else if (state == TelephonyManager.EXTRA_STATE_OFFHOOK) {
            isIncoming = false
            lastState = TelephonyManager.EXTRA_STATE_OFFHOOK
        } else if (state == TelephonyManager.EXTRA_STATE_IDLE) {
            if (lastState == TelephonyManager.EXTRA_STATE_RINGING && isIncoming) {
                val caller = ringingNumber ?: "Unknown"
                enqueueMissedCall(context, caller)
            }
            isIncoming = false
            ringingNumber = null
            lastState = TelephonyManager.EXTRA_STATE_IDLE
        }
    }

    private fun enqueueMissedCall(context: Context, callerNumber: String) {
        val now = System.currentTimeMillis()
        val df = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US).apply {
            timeZone = TimeZone.getTimeZone("UTC")
        }
        val occurredAt = df.format(Date(now))
        val externalId = "call:$callerNumber:$now"

        val payload = JSONObject().apply {
            put("source", "missed_call")
            put("external_id", externalId)
            put("thread_key", "call:$callerNumber")
            put("app_package", "com.android.dialer")
            put("sender_name", callerNumber)
            put("content", "مكالمة فائتة من $callerNumber")
            put("reply_capable", false)
            put("occurred_at", occurredAt)
        }

        try {
            val db = OutboxDbHelper.getInstance(context)
            db.enqueueEvent("missed_call", externalId, payload)
            Log.d(TAG, "Enqueued missed call from $callerNumber")
            OutboxSyncWorker.enqueueImmediateSync(context)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to enqueue missed call event", e)
        }
    }

    private fun handleSms(context: Context, intent: Intent) {
        val messages = Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return
        if (messages.isEmpty()) return

        val fullBody = StringBuilder()
        var sender = ""
        var timestamp = System.currentTimeMillis()

        for (msg in messages) {
            sender = msg.displayOriginatingAddress ?: msg.originatingAddress ?: "Unknown"
            fullBody.append(msg.displayMessageBody ?: msg.messageBody ?: "")
            timestamp = msg.timestampMillis
        }

        val df = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US).apply {
            timeZone = TimeZone.getTimeZone("UTC")
        }
        val occurredAt = df.format(Date(timestamp))
        val externalId = "sms:$sender:$timestamp"

        val payload = JSONObject().apply {
            put("source", "sms")
            put("external_id", externalId)
            put("thread_key", "sms:$sender")
            put("app_package", "com.android.mms")
            put("sender_name", sender)
            put("content", fullBody.toString())
            put("reply_capable", false)
            put("occurred_at", occurredAt)
        }

        try {
            val db = OutboxDbHelper.getInstance(context)
            db.enqueueEvent("sms", externalId, payload)
            Log.d(TAG, "Enqueued SMS from $sender")
            OutboxSyncWorker.enqueueImmediateSync(context)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to enqueue SMS event", e)
        }
    }
}
