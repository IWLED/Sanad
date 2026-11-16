package app.secretary.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.secretary.core.network.ActionPreview
import app.secretary.core.network.ServerWsEvent

@Composable
fun HitlCard(
    actionRequest: ServerWsEvent.ActionRequest,
    currentStatus: String? = null,
    onApprove: (actionId: String, version: Int, argsHash: String, editedText: String?) -> Unit,
    onReject: (actionId: String, version: Int, argsHash: String) -> Unit,
    modifier: Modifier = Modifier
) {
    val preview = actionRequest.preview
    val isT3 = actionRequest.riskTier == 3
    var isEditing by remember { mutableStateOf(false) }
    var editedDraft by remember(actionRequest.actionId) { mutableStateOf(preview.draftText) }

    val statusText = currentStatus ?: "PENDING_APPROVAL"
    val isPending = statusText == "PENDING_APPROVAL"

    Card(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = 8.dp),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant
        ),
        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp)
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp)
        ) {
            // 1. رأس البطاقة: العنوان ومستوى الخطورة وحالة التنفيذ
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = preview.title,
                    fontWeight = FontWeight.Bold,
                    fontSize = 16.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )

                Row(verticalAlignment = Alignment.CenterVertically) {
                    val badgeColor = if (isT3) Color(0xFFD32F2F) else Color(0xFFF57C00)
                    val tierLabel = if (isT3) "مستوى 3 (بصمة)" else "مستوى 2"

                    Box(
                        modifier = Modifier
                            .clip(RoundedCornerShape(8.dp))
                            .background(badgeColor)
                            .padding(horizontal = 8.dp, vertical = 4.dp)
                    ) {
                        Text(
                            text = tierLabel,
                            color = Color.White,
                            fontSize = 11.sp,
                            fontWeight = FontWeight.Bold
                        )
                    }

                    if (!isPending) {
                        Spacer(modifier = Modifier.width(6.dp))
                        val statusColor = when (statusText) {
                            "EXECUTED", "APPROVED" -> Color(0xFF2E7D32)
                            "REJECTED", "CANCELLED", "FAILED" -> Color(0xFFC62828)
                            else -> Color.Gray
                        }
                        Text(
                            text = statusText,
                            color = statusColor,
                            fontSize = 12.sp,
                            fontWeight = FontWeight.Bold
                        )
                    }
                }
            }

            // 2. المستقبل (إن وُجد)
            preview.recipient?.let { recipient ->
                Spacer(modifier = Modifier.height(8.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = "المستقبل: ",
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 13.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.8f)
                    )
                    Text(
                        text = recipient.name + (recipient.phone?.let { " ($it)" } ?: ""),
                        fontSize = 13.sp,
                        color = MaterialTheme.colorScheme.primary
                    )
                }
            }

            // 3. سياق المحادثة السابق (Thread context)
            if (preview.threadContext.isNotEmpty()) {
                Spacer(modifier = Modifier.height(10.dp))
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(8.dp))
                        .background(MaterialTheme.colorScheme.surface.copy(alpha = 0.5f))
                        .padding(8.dp)
                ) {
                    Text(
                        text = "السياق الأخير:",
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold,
                        color = Color.Gray
                    )
                    preview.threadContext.takeLast(3).forEach { msg ->
                        Text(
                            text = "${msg.who}: ${msg.text}",
                            fontSize = 12.sp,
                            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
                            maxLines = 1
                        )
                    }
                }
            }

            // 4. نص المسودة (Draft text) مع دعم التعديل
            Spacer(modifier = Modifier.height(12.dp))
            if (isEditing && isPending) {
                OutlinedTextField(
                    value = editedDraft,
                    onValueChange = { editedDraft = it },
                    label = { Text("تعديل المسودة") },
                    modifier = Modifier.fillMaxWidth(),
                    minLines = 2,
                    maxLines = 6
                )
            } else {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(8.dp))
                        .background(MaterialTheme.colorScheme.surface)
                        .border(
                            1.dp,
                            MaterialTheme.colorScheme.outline.copy(alpha = 0.2f),
                            RoundedCornerShape(8.dp)
                        )
                        .padding(12.dp)
                ) {
                    Text(
                        text = editedDraft,
                        fontSize = 14.sp,
                        color = MaterialTheme.colorScheme.onSurface
                    )
                }
            }

            // 5. التحذيرات الأمنية وDLP إن وُجدت
            if (preview.warnings.isNotEmpty()) {
                Spacer(modifier = Modifier.height(10.dp))
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(8.dp))
                        .background(Color(0xFFFFF3E0))
                        .padding(8.dp)
                ) {
                    preview.warnings.forEach { warning ->
                        Text(
                            text = "⚠️ $warning",
                            fontSize = 12.sp,
                            color = Color(0xFFE65100),
                            fontWeight = FontWeight.Medium
                        )
                    }
                }
            }

            // 6. أزرار التحكم والاعتماد [اعتماد] [تعديل] [إلغاء]
            if (isPending) {
                Spacer(modifier = Modifier.height(14.dp))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.End
                ) {
                    OutlinedButton(
                        onClick = {
                            onReject(
                                actionRequest.actionId,
                                actionRequest.version,
                                actionRequest.argsHash
                            )
                        },
                        colors = ButtonDefaults.outlinedButtonColors(
                            contentColor = Color(0xFFC62828)
                        )
                    ) {
                        Text("إلغاء")
                    }

                    Spacer(modifier = Modifier.width(8.dp))

                    TextButton(
                        onClick = { isEditing = !isEditing }
                    ) {
                        Text(if (isEditing) "حفظ التعديل" else "تعديل")
                    }

                    Spacer(modifier = Modifier.width(8.dp))

                    Button(
                        onClick = {
                            val modifiedText = if (isEditing && editedDraft != preview.draftText) {
                                editedDraft
                            } else null
                            onApprove(
                                actionRequest.actionId,
                                actionRequest.version,
                                actionRequest.argsHash,
                                modifiedText
                            )
                        },
                        colors = ButtonDefaults.buttonColors(
                            containerColor = if (isT3) Color(0xFFD32F2F) else Color(0xFF2E7D32)
                        )
                    ) {
                        Text(if (isT3) "اعتماد (بصمة)" else "اعتماد")
                    }
                }
            }
        }
    }
}
