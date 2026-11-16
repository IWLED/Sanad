package app.secretary.outbox

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import org.json.JSONObject

data class OutboxItem(
    val id: Long,
    val source: String,
    val externalId: String,
    val payloadJson: String,
    val createdAt: Long,
    val retryCount: Int
)

class OutboxDbHelper(context: Context) : SQLiteOpenHelper(context, DATABASE_NAME, null, DATABASE_VERSION) {

    companion object {
        const val DATABASE_NAME = "sanad_outbox.db"
        const val DATABASE_VERSION = 1
        const val TABLE_OUTBOX = "outbox_events"

        const val COL_ID = "id"
        const val COL_SOURCE = "source"
        const val COL_EXTERNAL_ID = "external_id"
        const val COL_PAYLOAD = "payload_json"
        const val COL_CREATED_AT = "created_at"
        const val COL_RETRY_COUNT = "retry_count"

        @Volatile
        private var instance: OutboxDbHelper? = null

        fun getInstance(context: Context): OutboxDbHelper {
            return instance ?: synchronized(this) {
                instance ?: OutboxDbHelper(context.applicationContext).also { instance = it }
            }
        }
    }

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """
            CREATE TABLE IF NOT EXISTS $TABLE_OUTBOX (
                $COL_ID INTEGER PRIMARY KEY AUTOINCREMENT,
                $COL_SOURCE TEXT NOT NULL,
                $COL_EXTERNAL_ID TEXT NOT NULL,
                $COL_PAYLOAD TEXT NOT NULL,
                $COL_CREATED_AT INTEGER NOT NULL,
                $COL_RETRY_COUNT INTEGER DEFAULT 0,
                UNIQUE($COL_SOURCE, $COL_EXTERNAL_ID) ON CONFLICT IGNORE
            )
            """.trimIndent()
        )
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        db.execSQL("DROP TABLE IF EXISTS $TABLE_OUTBOX")
        onCreate(db)
    }

    fun enqueueEvent(source: String, externalId: String, payload: JSONObject): Long {
        val db = writableDatabase
        val values = ContentValues().apply {
            put(COL_SOURCE, source)
            put(COL_EXTERNAL_ID, externalId)
            put(COL_PAYLOAD, payload.toString())
            put(COL_CREATED_AT, System.currentTimeMillis())
            put(COL_RETRY_COUNT, 0)
        }
        return db.insertWithOnConflict(TABLE_OUTBOX, null, values, SQLiteDatabase.CONFLICT_IGNORE)
    }

    fun getPendingEvents(limit: Int = 20): List<OutboxItem> {
        val db = readableDatabase
        val items = mutableListOf<OutboxItem>()
        val cursor = db.query(
            TABLE_OUTBOX,
            arrayOf(COL_ID, COL_SOURCE, COL_EXTERNAL_ID, COL_PAYLOAD, COL_CREATED_AT, COL_RETRY_COUNT),
            null, null, null, null,
            "$COL_CREATED_AT ASC",
            limit.toString()
        )

        cursor.use { c ->
            val idIdx = c.getColumnIndexOrThrow(COL_ID)
            val srcIdx = c.getColumnIndexOrThrow(COL_SOURCE)
            val extIdx = c.getColumnIndexOrThrow(COL_EXTERNAL_ID)
            val payloadIdx = c.getColumnIndexOrThrow(COL_PAYLOAD)
            val createdIdx = c.getColumnIndexOrThrow(COL_CREATED_AT)
            val retryIdx = c.getColumnIndexOrThrow(COL_RETRY_COUNT)

            while (c.moveToNext()) {
                items.add(
                    OutboxItem(
                        id = c.getLong(idIdx),
                        source = c.getString(srcIdx),
                        externalId = c.getString(extIdx),
                        payloadJson = c.getString(payloadIdx),
                        createdAt = c.getLong(createdIdx),
                        retryCount = c.getInt(retryIdx)
                    )
                )
            }
        }
        return items
    }

    fun deleteEvents(ids: List<Long>) {
        if (ids.isEmpty()) return
        val db = writableDatabase
        val placeholders = ids.joinToString(",") { "?" }
        val args = ids.map { it.toString() }.toTypedArray()
        db.delete(TABLE_OUTBOX, "$COL_ID IN ($placeholders)", args)
    }

    fun incrementRetry(id: Long) {
        val db = writableDatabase
        db.execSQL("UPDATE $TABLE_OUTBOX SET $COL_RETRY_COUNT = $COL_RETRY_COUNT + 1 WHERE $COL_ID = ?", arrayOf(id.toString()))
    }

    fun getPendingCount(): Long {
        val db = readableDatabase
        val cursor = db.rawQuery("SELECT COUNT(*) FROM $TABLE_OUTBOX", null)
        return cursor.use {
            if (it.moveToFirst()) it.getLong(0) else 0L
        }
    }
}
