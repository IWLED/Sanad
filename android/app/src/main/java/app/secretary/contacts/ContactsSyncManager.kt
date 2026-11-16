package app.secretary.contacts

import android.content.Context
import android.provider.ContactsContract
import android.util.Log
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

object ContactsSyncManager {
    private const val TAG = "ContactsSyncManager"
    private val jsonMediaType = "application/json; charset=utf-8".toMediaType()

    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .build()

    suspend fun syncDeviceContacts(context: Context): Result<Int> = withContext(Dispatchers.IO) {
        val token = SessionManager.getAccessToken(context)
        val serverUrl = SessionManager.getServerUrl(context)

        if (token == null) {
            return@withContext Result.failure(IllegalStateException("الجهاز غير مقترن (لا يوجد رمز جلسة)"))
        }

        try {
            val contactsMap = mutableMapOf<String, MutableList<String>>() // Name -> Phones
            val starredSet = mutableSetOf<String>()

            val resolver = context.contentResolver
            val uri = ContactsContract.CommonDataKinds.Phone.CONTENT_URI
            val projection = arrayOf(
                ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME,
                ContactsContract.CommonDataKinds.Phone.NUMBER,
                ContactsContract.CommonDataKinds.Phone.STARRED
            )

            resolver.query(uri, projection, null, null, null)?.use { cursor ->
                val nameIdx = cursor.getColumnIndex(ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME)
                val numIdx = cursor.getColumnIndex(ContactsContract.CommonDataKinds.Phone.NUMBER)
                val starIdx = cursor.getColumnIndex(ContactsContract.CommonDataKinds.Phone.STARRED)

                while (cursor.moveToNext()) {
                    val name = if (nameIdx != -1) cursor.getString(nameIdx) else null
                    val number = if (numIdx != -1) cursor.getString(numIdx) else null
                    val starred = if (starIdx != -1) cursor.getInt(starIdx) == 1 else false

                    if (!name.isNullOrBlank() && !number.isNullOrBlank()) {
                        val cleanName = name.trim()
                        val list = contactsMap.getOrPut(cleanName) { mutableListOf() }
                        if (!list.contains(number.trim())) {
                            list.add(number.trim())
                        }
                        if (starred) {
                            starredSet.add(cleanName)
                        }
                    }
                }
            }

            if (contactsMap.isEmpty()) {
                Log.d(TAG, "No contacts found to sync")
                return@withContext Result.success(0)
            }

            val jsonArray = JSONArray()
            for ((name, phones) in contactsMap) {
                val item = JSONObject().apply {
                    put("raw_name", name)
                    val phonesArray = JSONArray()
                    phones.forEach { phonesArray.put(it) }
                    put("phones", phonesArray)
                    put("aliases", JSONArray())
                    put("is_vip", starredSet.contains(name))
                    put("starred", starredSet.contains(name))
                }
                jsonArray.put(item)
            }

            val request = Request.Builder()
                .url("${serverUrl.trimEnd('/')}/v1/contacts/sync")
                .header("Authorization", "Bearer $token")
                .post(jsonArray.toString().toRequestBody(jsonMediaType))
                .build()

            val response = httpClient.newCall(request).execute()
            val body = response.body?.string() ?: ""

            if (response.isSuccessful) {
                val resObj = JSONObject(body)
                val total = resObj.optInt("synced_count", 0) + resObj.optInt("updated_count", 0)
                Log.i(TAG, "Contacts sync completed successfully: $total contacts processed")
                Result.success(total)
            } else {
                Log.e(TAG, "Contacts sync failed (${response.code}): $body")
                Result.failure(Exception("فشلت المزامنة (${response.code}): $body"))
            }
        } catch (e: Exception) {
            Log.e(TAG, "Contacts sync exception", e)
            Result.failure(e)
        }
    }
}
