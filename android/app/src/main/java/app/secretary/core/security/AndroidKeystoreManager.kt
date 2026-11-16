package app.secretary.core.security

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.Signature
import java.security.spec.ECGenParameterSpec

/**
 * مدير مفاتيح الجهاز داخل Android Keystore المشفر بالعتاد الصلب (R-12, Section 8.1).
 * يولد زوج مفاتيح EC P-256 ويوقع طلبات التجديد لإثبات الحيازة (Proof-of-Possession).
 */
class AndroidKeystoreManager(
    private val keyAlias: String = DEFAULT_KEY_ALIAS
) {
    companion object {
        const val DEFAULT_KEY_ALIAS = "sanad_device_ec_key"
        private const val ANDROID_KEYSTORE = "AndroidKeyStore"
        private const val SIGNING_ALGORITHM = "SHA256withECDSA"
    }

    private val keyStore: KeyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply {
        load(null)
    }

    /**
     * الحصول على زوج المفاتيح أو توليده إذا لم يكن موجوداً مسبقاً.
     */
    fun getOrCreateKeyPair(): KeyPair {
        if (!keyStore.containsAlias(keyAlias)) {
            generateEcKeyPair()
        }
        val entry = keyStore.getEntry(keyAlias, null) as KeyStore.PrivateKeyEntry
        return KeyPair(entry.certificate.publicKey, entry.privateKey)
    }

    /**
     * تصدير المفتاح العام بصيغة PEM لإرساله للخادم أثناء الاقتران.
     */
    fun getPublicKeyPem(): String {
        val keyPair = getOrCreateKeyPair()
        val encoded = Base64.encodeToString(keyPair.public.encoded, Base64.NO_WRAP)
        return buildString {
            append("-----BEGIN PUBLIC KEY-----\n")
            // تقسيم السطور كل 64 محرف
            encoded.chunked(64).forEach { line ->
                append(line).append("\n")
            }
            append("-----END PUBLIC KEY-----\n")
        }
    }

    /**
     * توقيع رسالة (device_id|ts|nonce) بالمفتاح الخاص المحمي داخل الـ Keystore.
     */
    fun sign(data: ByteArray): String {
        val keyPair = getOrCreateKeyPair()
        val signature = Signature.getInstance(SIGNING_ALGORITHM).apply {
            initSign(keyPair.private)
            update(data)
        }
        val sigBytes = signature.sign()
        return Base64.encodeToString(sigBytes, Base64.NO_WRAP)
    }

    /**
     * توليد زوج مفاتيح EC P-256 مع محاولة استخدام StrongBox إن وُجد.
     */
    private fun generateEcKeyPair() {
        val kpg = KeyPairGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_EC,
            ANDROID_KEYSTORE
        )

        try {
            // محاولة استخدام StrongBox
            val spec = buildKeySpec(useStrongBox = true)
            kpg.initialize(spec)
            kpg.generateKeyPair()
        } catch (e: Exception) {
            // في حال عدم دعم StrongBox يتم الرجوع للـ TEE القياسي
            val fallbackSpec = buildKeySpec(useStrongBox = false)
            kpg.initialize(fallbackSpec)
            kpg.generateKeyPair()
        }
    }

    private fun buildKeySpec(useStrongBox: Boolean): KeyGenParameterSpec {
        val builder = KeyGenParameterSpec.Builder(
            keyAlias,
            KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY
        )
            .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
            .setDigests(KeyProperties.DIGEST_SHA256)
            .setUserAuthenticationRequired(false) // لا يتطلب بصمة لتجديد الجلسة في الخلفية

        if (useStrongBox) {
            builder.setIsStrongBoxBacked(true)
        }

        return builder.build()
    }
}
