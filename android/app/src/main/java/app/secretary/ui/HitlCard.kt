package app.secretary.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Fingerprint
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Security
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import app.secretary.core.network.ServerWsEvent
import app.secretary.ui.theme.StatusCritical
import app.secretary.ui.theme.StatusSuccess
import app.secretary.ui.theme.StatusWarning

/**
 * بطاقة اعتماد وتأكيد الإجراءات الحساسة (Human-In-The-Loop Approval Card - Section 11.2).
 * مصممة وفق أحدث معايير Material 3 بوضوح تام لمستوى المخاطر وتعديل المسودة والاعتماد.
 */
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

    ElevatedCard(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = 6.dp),
        shape = MaterialTheme.shapes.large,
        colors = CardDefaults.elevatedCardColors(
            containerColor = MaterialTheme.colorScheme.surface
        ),
        elevation = CardDefaults.elevatedCardElevation(defaultElevation = 2.dp)
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(18.dp)
        ) {
            // 1. رأس البطاقة: العنوان ومستوى الخطورة وحالة التنفيذ
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = preview.title,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onSurface,
                    modifier = Modifier.weight(1f)
                )

                Row(verticalAlignment = Alignment.CenterVertically) {
                    val badgeColor = if (isT3) StatusCritical else StatusWarning
                    val tierLabel = if (isT3) "مستوى 3 (بصمة)" else "مستوى 2 (تأكيد)"
                    val tierIcon = if (isT3) Icons.Default.Fingerprint else Icons.Default.Security

                    Surface(
                        shape = MaterialTheme.shapes.extraSmall,
                        color = badgeColor.copy(alpha = 0.12f)
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp)
                        ) {
                            Icon(
                                imageVector = tierIcon,
                                contentDescription = null,
                                tint = badgeColor,
                                modifier = Modifier.size(14.dp)
                            )
                            Spacer(modifier = Modifier.width(4.dp))
                            Text(
                                text = tierLabel,
                                color = badgeColor,
                                style = MaterialTheme.typography.labelSmall,
                                fontWeight = FontWeight.Bold
                            )
                        }
                    }

                    if (!isPending) {
                        Spacer(modifier = Modifier.width(6.dp))
                        val statusColor = when (statusText) {
                            "EXECUTED", "APPROVED" -> StatusSuccess
                            "REJECTED", "CANCELLED", "FAILED" -> StatusCritical
                            else -> MaterialTheme.colorScheme.outline
                        }
                        Surface(
                            shape = MaterialTheme.shapes.extraSmall,
                            color = statusColor.copy(alpha = 0.12f)
                        ) {
                            Text(
                                text = when (statusText) {
                                    "EXECUTED" -> "تم التنفيذ"
                                    "APPROVED" -> "معتمد"
                                    "REJECTED" -> "مرفوض"
                                    "FAILED" -> "فشل التنفيذ"
                                    else -> statusText
                                },
                                color = statusColor,
                                style = MaterialTheme.typography.labelSmall,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp)
                            )
                        }
                    }
                }
            }

            // 2. المستقبل (إن وُجد)
            preview.recipient?.let { recipient ->
                Spacer(modifier = Modifier.height(10.dp))
                Surface(
                    shape = MaterialTheme.shapes.small,
                    color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp)
                    ) {
                        Icon(
                            imageVector = Icons.Default.Person,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.size(16.dp)
                        )
                        Spacer(modifier = Modifier.width(6.dp))
                        Text(
                            text = "المستقبل: ",
                            style = MaterialTheme.typography.bodySmall,
                            fontWeight = FontWeight.SemiBold,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        Text(
                            text = recipient.name + (recipient.phone?.let { " ($it)" } ?: ""),
                            style = MaterialTheme.typography.bodySmall,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.primary
                        )
                    }
                }
            }

            // 3. سياق المحادثة السابق (Thread context)
            if (preview.threadContext.isNotEmpty()) {
                Spacer(modifier = Modifier.height(10.dp))
                Surface(
                    shape = MaterialTheme.shapes.small,
                    color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.35f),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(modifier = Modifier.padding(10.dp)) {
                        Text(
                            text = "سياق الرسائل السابقة:",
                            style = MaterialTheme.typography.labelSmall,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        Spacer(modifier = Modifier.height(4.dp))
                        preview.threadContext.takeLast(2).forEach { msg ->
                            Text(
                                text = "${msg.who}: ${msg.text}",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.8f),
                                maxLines = 1
                            )
                        }
                    }
                }
            }

            // 4. نص المسودة (Draft text) مع دعم التعديل
            Spacer(modifier = Modifier.height(12.dp))
            if (isEditing && isPending) {
                OutlinedTextField(
                    value = editedDraft,
                    onValueChange = { editedDraft = it },
                    label = { Text("تعديل نص الرسالة المقترح") },
                    modifier = Modifier.fillMaxWidth(),
                    shape = MaterialTheme.shapes.small,
                    minLines = 3,
                    maxLines = 6
                )
            } else {
                Surface(
                    shape = MaterialTheme.shapes.medium,
                    color = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.35f),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(modifier = Modifier.padding(12.dp)) {
                        Text(
                            text = "النص المقترح:",
                            style = MaterialTheme.typography.labelSmall,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.primary
                        )
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = editedDraft,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurface
                        )
                    }
                }
            }

            // 5. شريط أزرار اتخاذ القرار
            if (isPending) {
                Spacer(modifier = Modifier.height(16.dp))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    TextButton(
                        onClick = { isEditing = !isEditing },
                        shape = MaterialTheme.shapes.small
                    ) {
                        Icon(
                            imageVector = Icons.Default.Edit,
                            contentDescription = null,
                            modifier = Modifier.size(16.dp)
                        )
                        Spacer(modifier = Modifier.width(4.dp))
                        Text(
                            text = if (isEditing) "حفظ التعديل" else "تعديل النص",
                            style = MaterialTheme.typography.labelMedium
                        )
                    }

                    Row(verticalAlignment = Alignment.CenterVertically) {
                        OutlinedButton(
                            onClick = {
                                onReject(actionRequest.actionId, actionRequest.version, actionRequest.argsHash)
                            },
                            shape = MaterialTheme.shapes.small,
                            colors = ButtonDefaults.outlinedButtonColors(
                                contentColor = StatusCritical
                            )
                        ) {
                            Icon(
                                imageVector = Icons.Default.Close,
                                contentDescription = null,
                                modifier = Modifier.size(16.dp)
                            )
                            Spacer(modifier = Modifier.width(4.dp))
                            Text("رفض", style = MaterialTheme.typography.labelMedium)
                        }

                        Spacer(modifier = Modifier.width(8.dp))

                        Button(
                            onClick = {
                                val textToSend = if (isEditing) editedDraft else null
                                onApprove(actionRequest.actionId, actionRequest.version, actionRequest.argsHash, textToSend)
                            },
                            shape = MaterialTheme.shapes.small
                        ) {
                            Icon(
                                imageVector = if (isT3) Icons.Default.Fingerprint else Icons.Default.Check,
                                contentDescription = null,
                                modifier = Modifier.size(16.dp)
                            )
                            Spacer(modifier = Modifier.width(4.dp))
                            Text(
                                text = if (isT3) "اعتماد بالبصمة" else "اعتماد وتنفيذ",
                                style = MaterialTheme.typography.labelMedium
                            )
                        }
                    }
                }
            }
        }
    }
}
