package app.secretary.outbox

import android.content.Context
import android.util.Log
import androidx.work.*
import app.secretary.core.network.SessionManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class OutboxSyncWorker(
    appContext: Context,
    workerParams: WorkerParameters
) : CoroutineWorker(appContext, workerParams) {

    companion object {
        private const val TAG = "OutboxSyncWorker"
        private const val UNIQUE_WORK_NAME = "sanad_outbox_sync"

        fun enqueueImmediateSync(context: Context) {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()

            val request = OneTimeWorkRequestBuilder<OutboxSyncWorker>()
                .setConstraints(constraints)
                .build()

            WorkManager.getInstance(context).enqueueUniqueWork(
                UNIQUE_WORK_NAME,
                ExistingWorkPolicy.REPLACE,
                request
            )
        }

        fun schedulePeriodicSync(context: Context) {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()

            val periodicRequest = PeriodicWorkRequestBuilder<OutboxSyncWorker>(15, TimeUnit.MINUTES)
                .setConstraints(constraints)
                .build()

            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                "sanad_outbox_periodic_sync",
                ExistingPeriodicWorkPolicy.KEEP,
                periodicRequest
            )
        }
    }

    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .build()

    private val jsonMediaType = "application/json; charset=utf-8".toMediaType()

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val token = SessionManager.getAccessToken(applicationContext)
        val serverUrl = SessionManager.getServerUrl(applicationContext)

        if (token == null) {
            Log.w(TAG, "No auth token available, postponing outbox sync")
            return@withContext Result.retry()
        }

        val db = OutboxDbHelper.getInstance(applicationContext)
        val pending = db.getPendingEvents(limit = 30)

        if (pending.isEmpty()) {
            return@withContext Result.success()
        }

        try {
            val jsonArray = JSONArray()
            val itemIds = mutableListOf<Long>()

            for (item in pending) {
                jsonArray.put(JSONObject(item.payloadJson))
                itemIds.add(item.id)
            }

            val request = Request.Builder()
                .url("${serverUrl.trimEnd('/')}/v1/ingest/events")
                .header("Authorization", "Bearer $token")
                .post(jsonArray.toString().toRequestBody(jsonMediaType))
                .build()

            val response = httpClient.newCall(request).execute()
            val body = response.body?.string() ?: ""

            if (response.isSuccessful) {
                Log.i(TAG, "Successfully synced ${itemIds.size} events to server: $body")
                db.deleteEvents(itemIds)
                Result.success()
            } else {
                Log.e(TAG, "Server returned error on ingest (${response.code}): $body")
                for (id in itemIds) {
                    db.incrementRetry(id)
                }
                Result.retry()
            }
        } catch (e: Exception) {
            Log.e(TAG, "Network failure while syncing outbox", e)
            for (item in pending) {
                db.incrementRetry(item.id)
            }
            Result.retry()
        }
    }
}
