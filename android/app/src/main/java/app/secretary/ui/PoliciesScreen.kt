package app.secretary.ui

import android.widget.Toast
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject

data class AppPolicyItem(
    val package_name: String,
    val label: String,
    var monitor: Boolean,
    var allow_reply: Boolean,
    val default_priority: String = "normal"
)

/**
 * شاشة إدارة سياسات التطبيقات المراقبة والسماح بالرد (Section 9.4 & Section 8.2).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PoliciesScreen(
    serverUrl: String,
    token: String,
    onBack: () -> Unit,
    modifier: Modifier = Modifier
) {
    val context = LocalContext.current
    val coroutineScope = rememberCoroutineScope()
    var isLoading by remember { mutableStateOf(true) }
    val policies = remember { mutableStateListOf<AppPolicyItem>() }

    // جلب السياسات الحالية من الخادم GET /v1/policies/apps
    LaunchedEffect(Unit) {
        val fetched = fetchAppPolicies(serverUrl, token)
        policies.clear()
        policies.addAll(fetched)
        isLoading = false
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("سياسات التطبيقات والردود") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Text("←", fontSize = 20.sp, fontWeight = FontWeight.Bold)
                    }
                }
            )
        },
        modifier = modifier
    ) { padding ->
        if (isLoading) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding),
                contentAlignment = Alignment.Center
            ) {
                CircularProgressIndicator()
            }
        } else {
            LazyColumn(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                item {
                    Text(
                        text = "التحكم في التطبيقات المسموح بمراقبة إشعاراتها واقتراح الردود عليها:",
                        fontSize = 14.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }

                items(policies) { item ->
                    Card(
                        shape = RoundedCornerShape(14.dp),
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.surfaceVariant
                        ),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(16.dp)
                        ) {
                            Text(
                                text = item.label,
                                fontWeight = FontWeight.Bold,
                                fontSize = 16.sp
                            )
                            Text(
                                text = item.package_name,
                                fontSize = 12.sp,
                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f)
                            )

                            Spacer(modifier = Modifier.height(12.dp))

                            // خيار مراقبة الإشعارات
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Text("مراقبة الإشعارات", fontSize = 14.sp)
                                Switch(
                                    checked = item.monitor,
                                    onCheckedChange = { checked ->
                                        item.monitor = checked
                                        coroutineScope.launch {
                                            updateAppPolicy(serverUrl, token, item)
                                        }
                                    }
                                )
                            }

                            // خيار السماح بالرد (Section 9.2)
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Text("السماح باقتراح الردود", fontSize = 14.sp)
                                Switch(
                                    checked = item.allow_reply,
                                    onCheckedChange = { checked ->
                                        item.allow_reply = checked
                                        coroutineScope.launch {
                                            updateAppPolicy(serverUrl, token, item)
                                        }
                                    }
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

private suspend fun fetchAppPolicies(serverUrl: String, token: String): List<AppPolicyItem> =
    withContext(Dispatchers.IO) {
        val list = mutableListOf<AppPolicyItem>()
        try {
            val client = OkHttpClient()
            val url = "${serverUrl.trimEnd('/')}/v1/policies/apps"
            val request = Request.Builder()
                .url(url)
                .addHeader("Authorization", "Bearer $token")
                .get()
                .build()

            val response = client.newCall(request).execute()
            if (response.isSuccessful) {
                val body = response.body?.string() ?: "[]"
                val jsonArr = JSONArray(body)
                for (i in 0 until jsonArr.length()) {
                    val obj = jsonArr.getJSONObject(i)
                    list.add(
                        AppPolicyItem(
                            package_name = obj.getString("package"),
                            label = obj.optString("label", obj.getString("package")),
                            monitor = obj.optInt("monitor", 0) == 1,
                            allow_reply = obj.optInt("allow_reply", 0) == 1,
                            default_priority = obj.optString("default_priority", "normal")
                        )
                    )
                }
            }
        } catch (_: Exception) {}
        list
    }

private suspend fun updateAppPolicy(serverUrl: String, token: String, item: AppPolicyItem): Boolean =
    withContext(Dispatchers.IO) {
        try {
            val client = OkHttpClient()
            val url = "${serverUrl.trimEnd('/')}/v1/policies/apps/${item.package_name}"
            val payload = JSONObject().apply {
                put("monitor", if (item.monitor) 1 else 0)
                put("allow_reply", if (item.allow_reply) 1 else 0)
                put("default_priority", item.default_priority)
            }
            val request = Request.Builder()
                .url(url)
                .addHeader("Authorization", "Bearer $token")
                .put(payload.toString().toRequestBody("application/json".toMediaType()))
                .build()

            val response = client.newCall(request).execute()
            response.isSuccessful
        } catch (_: Exception) {
            false
        }
    }
