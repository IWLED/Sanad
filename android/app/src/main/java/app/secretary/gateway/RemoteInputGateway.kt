package app.secretary.gateway

import android.app.Notification
import android.app.RemoteInput
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.util.Log

object RemoteInputGateway {
    private const val TAG = "RemoteInputGateway"

    // حفظ الإجراءات الفعالة بالـ thread_key أو notificationKey
    private val activeActions = mutableMapOf<String, Notification.Action>()

    fun registerAction(key: String, action: Notification.Action) {
        synchronized(activeActions) {
            activeActions[key] = action
        }
        Log.d(TAG, "Registered reply action for key: $key")
    }

    fun hasAction(key: String): Boolean {
        synchronized(activeActions) {
            return activeActions.containsKey(key)
        }
    }

    fun sendReply(context: Context, key: String, replyText: String): Boolean {
        val action = synchronized(activeActions) {
            activeActions[key]
        } ?: run {
            Log.w(TAG, "No active reply action found for key: $key")
            return false
        }

        val remoteInputs = action.remoteInputs
        if (remoteInputs.isNullOrEmpty()) {
            Log.w(TAG, "Action for key $key has no RemoteInputs")
            return false
        }

        return try {
            val intent = Intent()
            val bundle = Bundle()
            for (ri in remoteInputs) {
                bundle.putCharSequence(ri.resultKey, replyText)
            }
            RemoteInput.addResultsToIntent(remoteInputs, intent, bundle)
            action.actionIntent.send(context, 0, intent)
            Log.i(TAG, "Successfully sent RemoteInput reply for key: $key")
            true
        } catch (e: Exception) {
            Log.e(TAG, "Failed to send RemoteInput reply for key: $key", e)
            false
        }
    }
}
