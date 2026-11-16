package app.secretary

import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

/**
 * شاشة التجارب الميدانية وقياس سلوك الإشعارات والرد (Section 14 T-0.6).
 * تُستخدم لإجراء تجارب S1 (مصفوفة الإشعارات) وS2 (مصفوفة الرد) وS3 (بقاء الخدمة).
 */
class SpikeActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        setContent {
            MaterialTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    SpikeDashboardScreen()
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SpikeDashboardScreen() {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("أداة قياس سند الميدانية (Spike)") }
            )
        }
    ) { paddingValues ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            item {
                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text(
                            text = "معلومات بيئة الجهاز",
                            style = MaterialTheme.typography.titleMedium
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        Text("الشركة والنوع: ${Build.MANUFACTURER} ${Build.MODEL}")
                        Text("إصدار أندرويد: ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})")
                        Text("بنية المعالج: ${Build.SUPPORTED_ABIS.joinToString()}")
                    }
                }
            }

            item {
                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text(
                            text = "التجارب الميدانية المقررة (Spikes S1-S5)",
                            style = MaterialTheme.typography.titleMedium
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        Text("• S1: التقاط الإشعارات (واتساب، تيليجرام، SMS، Gmail)")
                        Text("• S2: مصفوفة الرد المباشر RemoteInput وسلوك الاقتباس")
                        Text("• S3: قياس استقرار الخدمة 48 ساعة واستهلاك البطارية")
                        Text("• S4: تسجيلات تقييم دقة تفريغ الصوت الخليجي STT")
                        Text("• S5: تقييم النماذج اللغوية والاستجابة العربية")
                    }
                }
            }

            item {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Button(
                        onClick = { /* تصدير JSON */ },
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("تصدير النتائج (JSON)")
                    }
                    OutlinedButton(
                        onClick = { /* مسح السجلات */ },
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("إعادة ضبط")
                    }
                }
            }
        }
    }
}
