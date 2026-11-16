package app.secretary.fakemessenger

import android.app.NotificationManager
import android.app.RemoteInput
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.widget.Toast
import androidx.core.app.NotificationCompat
import androidx.core.app.Person

class ReplyReceiver : BroadcastReceiver() {
    companion object {
        const val KEY_TEXT_REPLY = "key_text_reply"
        const val NOTIFICATION_ID = 1001
        const val CHANNEL_ID = "fake_chat_channel"
    }

    override fun onReceive(context: Context, intent: Intent) {
        val remoteInput = RemoteInput.getResultsFromIntent(intent)
        val replyText = remoteInput?.getCharSequence(KEY_TEXT_REPLY)?.toString()

        if (!replyText.isNullOrBlank()) {
            Toast.makeText(context, "وصل الرد بنجاح: $replyText", Toast.LENGTH_LONG).show()

            // تحديث الإشعار لإثبات تسلم الرد
            val notificationManager =
                context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

            val user = Person.Builder().setName("أنت").build()
            val sender = Person.Builder().setName("أبو فهد").build()

            val style = NotificationCompat.MessagingStyle(user)
                .addMessage("وينك يا غالي؟", System.currentTimeMillis() - 60000, sender)
                .addMessage(replyText, System.currentTimeMillis(), user)

            val updatedNotification = NotificationCompat.Builder(context, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.sym_action_chat)
                .setStyle(style)
                .setContentTitle("محادثة أبو فهد")
                .setContentText("أنت: $replyText")
                .build()

            notificationManager.notify(NOTIFICATION_ID, updatedNotification)
        }
    }
}
