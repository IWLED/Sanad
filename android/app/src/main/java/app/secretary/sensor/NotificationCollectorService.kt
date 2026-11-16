package app.secretary.sensor

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import app.secretary.gateway.RemoteInputGateway
import app.secretary.outbox.OutboxDbHelper
import app.secretary.outbox.OutboxSyncWorker
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

class NotificationCollectorService : NotificationListenerService() {

    companion object {
        private const val TAG = "NotificationCollector"

        // حزم معفاة ومستبعدة (مثل إشعارات تطبيق سند نفسه)
        private val IGNORED_PACKAGES = setOf(
            "app.secretary",
            "android",
            "com.android.systemui"
        )
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        super.onNotificationPosted(sbn)
        if (sbn == null) return

        val pkg = sbn.packageName
        if (IGNORED_PACKAGES.contains(pkg)) {
            return
        }

        val notification = sbn.notification ?: return
        val extras = notification.extras ?: return

        val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString()?.trim() ?: ""
        val text = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString()?.trim() ?: ""
        val bigText = extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString()?.trim()
        val conversationTitle = extras.getCharSequence(Notification.EXTRA_CONVERSATION_TITLE)?.toString()?.trim()
        val isGroup = extras.getBoolean(Notification.EXTRA_IS_GROUP_CONVERSATION, false)

        val content = if (!bigText.isNullOrEmpty()) bigText else text
        if (content.isEmpty() && title.isEmpty()) {
            return
        }

        // البحث عن إجراء الرد (RemoteInput)
        var replyCapable = false
        val actions = notification.actions
        val threadKey = "$pkg:${sbn.id}"

        if (actions != null) {
            for (action in actions) {
                if (action.remoteInputs != null && action.remoteInputs.isNotEmpty()) {
                    RemoteInputGateway.registerAction(threadKey, action)
                    RemoteInputGateway.registerAction(sbn.key, action)
                    replyCapable = true
                    break
                }
            }
        }

        val df = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US)
        df.timeZone = TimeZone.getTimeZone("UTC")
        val occurredAt = df.format(Date(sbn.postTime))
        val externalId = "$pkg:${sbn.id}:${sbn.postTime}"

        val payload = JSONObject().apply {
            put("source", "notification")
            put("external_id", externalId)
            put("thread_key", threadKey)
            put("app_package", pkg)
            put("sender_name", title)
            put("is_group", isGroup)
            if (!conversationTitle.isNullOrEmpty()) {
                put("context_title", conversationTitle)
            }
            put("content", content)
            put("reply_capable", replyCapable)
            put("occurred_at", occurredAt)
        }

        try {
            val db = OutboxDbHelper.getInstance(this)
            val rowId = db.enqueueEvent("notification", externalId, payload)
            if (rowId != -1L) {
                Log.d(TAG, "Enqueued notification from $pkg: $title")
                OutboxSyncWorker.enqueueImmediateSync(this)
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to enqueue notification event", e)
        }
    }
}
