# دليل إدارة الأسرار (deploy/secrets/README.md)
> تنفيذاً للقواعد 0.2-6 و R-14: يُمنع وضع أي مفاتيح حقيقية في المستودع. يتم حقن الأسرار عبر Docker Secrets أو ملفات مشفرة خارج Git.

الملفات المطلوبة للتشغيل في بيئة الإنتاج داخل هذا المجلد:
* `jwt_signing_key`: مفتاح التوقيع الخاص لرموز JWT (Ed25519 أو EC P-256 PEM).
* `enc_key`: مفتاح تشفير قاعدة البيانات والرموز (32 بايت عشوائي AES-256 hex/base64).
* `pepper`: ملح تجزئة رموز التحديث Refresh Tokens.
* `fcm_service_account.json`: ملف حساب خدمة Firebase Cloud Messaging (JSON).
* `llm_key_a`: مفتاح المزود الأساسي للذكاء الاصطناعي (أو يُترك فارغاً عند استخدام OmniRoute المحلي).
* `llm_key_b`: مفتاح المزود الثانوي.
* `cf_tunnel_token`: رمز نفق Cloudflare Tunnel المدار.
