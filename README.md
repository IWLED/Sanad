# 🤖 سند (Sanad) — السكرتير الشخصي الذكي (Personal AI Secretary)

[![Release](https://img.shields.io/github/v/release/IWLED/Sanad?display_name=tag&include_prereleases&style=flat-square&color=2ea44f)](https://github.com/IWLED/Sanad/releases)
[![Android](https://img.shields.io/badge/Android-11%2B%20(API%2030%2B)-green?style=flat-square&logo=android)](https://developer.android.com)
[![Python](https://img.shields.io/badge/Python-3.12-blue?style=flat-square&logo=python)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker)](https://www.docker.com)
[![Obtainium](https://img.shields.io/badge/Obtainium-Add%20to%20Obtainium-purple?style=flat-square&logo=android)](obtainium://app/https://github.com/IWLED/Sanad)

**سند** هو سكرتير ذكاء اصطناعي شخصي متكامل ومستضاف ذاتياً (Self-Hosted)، مصمم للعمل في خادمك المنزلي مع تطبيق أندرويد خاص مبني بلغة Kotlin وJetpack Compose. يقوم بجمع الإشعارات والرسائل والمكالمات الواردة بأمان، وتلخيصها وتصنيفها حسب الأولوية والعائلة، وصياغة الردود والمستندات ولا ينفّذ أي إجراء خارجي إلا بعد اعتمادك وموافقتك البشرية الصريحة (**Human-in-the-Loop**).

---

## 📱 تطبيق الأندرويد والتحديث التلقائي عبر Obtainium

تطبيق سند مصمم خصيصاً ليدعم التثبيت والتحديث التلقائي المباشر من المصدر عبر تطبيق **[Obtainium](https://github.com/ImranR98/Obtainium)** دون الحاجة إلى متجر Google Play.

### 🚀 خطوات إضافة التطبيق إلى Obtainium:

1. حمّل وثبّت تطبيق **Obtainium** على هاتفك (من [صفحة إصدارات Obtainium](https://github.com/ImranR98/Obtainium/releases)).
2. افتح تطبيق Obtainium واضغط على **«Add App»** (إضافة تطبيق).
3. ضع رابط المستودع في خانة الرابط:
   ```text
   https://github.com/IWLED/Sanad
   ```
4. اضغط على **«Add»**؛ سيقوم Obtainium فوراً بجلب أحدث ملف `Sanad.apk` وتثبيته.
5. سيتولى Obtainium إشعارك وتحديث التطبيق تلقائياً في الخلفية عند صدور أي إصدار جديد!

> [!TIP]
> **إذا كان المستودع خاصاً (Private):**
> ادخل إلى إعدادات Obtainium -> فعّل خيار `Use GitHub Credentials` وأدخل توكن GitHub الشخصي (Personal Access Token) بصلاحية `repo`.

---

## ✨ المميزات الرئيسية لسند

- **🛡️ الاعتماد البشري الصارم (HITL - Human-in-the-Loop):**
  لا يرسل السكرتير أي رد أو بريد أو ملف إلا بعد عرض بطاقة مراجعة تفاعلية (HitlCard) عليك لتعتمدها أو تعدلها، مع دعم تأكيد البصمة الحيوية (Biometrics) للعمليات الحساسة.
- **💬 الرد المباشر عبر إشعارات النظام (RemoteInput Gateway):**
  الردود على واتساب وتيليجرام وSMS تُنفّذ محلياً من نفس التطبيقات الرسمية عبر خدمة النظام الآمنة، بدون أي روبوتات غير رسمية قد تعرض حساباتك للحظر.
- **🌅 الإيجاز الصباحي وسيناريو الاستيقاظ:**
  عند سؤالك «وش صار اليوم؟» أو عند حلول موعد الإيجاز الصباحي المجدول (07:30 صباحاً)، يقدم لك ملخصاً مقسماً:
  - ⚡ **عاجل والعائلة**
  - 📞 **المكالمات الفائتة**
  - 💬 **الرسائل بانتظار الرد**
  - ℹ️ **تنبيهات ومعلومات عامة**
- **📄 توليد وقراءة المستندات المكتبية:**
  - توليد ملفات Word (`.docx`) وجداول Excel (`.xlsx`) وعروض PowerPoint (`.pptx`) باللغة العربية واتجاه RTL.
  - إرفاق المستندات وقراءتها وتحليلها واستخراج نصوصها عبر الجوال.
- **🎙️ الأوامر الصوتية والتفريغ (STT):**
  دعم الأوامر الصوتية والتفريغ السريع عبر نماذج Whisper المتوافقة محلياً، مع نطق الإيجاز صوتياً (TTS).
- **🔒 الخصوصية والحماية الكاملة:**
  - تصفية وحجب الأسرار والـ OTP تلقائياً عبر محرك DLP.
  - تشفير الجلسات والمفاتيح في Android Keystore وAES-GCM.
  - سجل تدقيق غير قابل للتلاعب مشفر بسلسلة تجزئة (Hash Chain).

---

## 🛠️ تشغيل الخادم المنزلي (Server Deployment)

### المتطلبات:
- Docker و Docker Compose.
- نظام تشغيل Linux / ZimaOS / CasaOS / Ubuntu.
- اتصال محلي أو نفق Cloudflare Tunnel.

### خطوات التشغيل السريع:

```bash
# 1. الدخول لمجلد النشر
cd deploy

# 2. إنشاء ملف الإعدادات
cp .env.example .env

# 3. تشغيل الحاويات
docker compose up -d --build
```

### فحص صحة النظام وتشخيص السيرفر:

يحتوي مجلد `scripts/` على أدوات تشخيص وصيانة متكاملة:

```bash
# فحص صحة الحاويات والخدمات وقاعدة البيانات
./scripts/health_check.sh

# أخذ نسخة احتياطية فورية متسقة من قاعدة البيانات
./scripts/backup.sh

# استعادة نسخة احتياطية
./scripts/restore.sh /path/to/backup.tar.gz
```

---

## 📁 هيكل المستودع

```text
├── android/          # تطبيق أندرويد (Kotlin + Jetpack Compose + Room/WorkManager)
├── server/           # خادم بايثون (FastAPI, Worker, LLM Agent Loop, HITL Engine)
├── deploy/           # إعدادات Docker Compose و CasaOS والنفق
├── scripts/          # سكربتات النسخ الاحتياطي والفحص الصحي والاستعادة
├── docs/             # التوثيق الشامل، سجل التقدم، القرارات المعمارية (ADR)
└── shared/           # المخططات المشتركة وبروتوكولات الرسائل (Schemas)
```

---

## 📄 الترخيص
تم تطوير هذا المشروع للاستخدام الشخصي المستضاف ذاتياً وفق معايير الأمان والخصوصية الصارمة.
