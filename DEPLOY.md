# نشر المشروع على Vercel — دليل كامل

هذا المشروع أصبح جاهزاً للعمل بنظام **Webhook** (لا polling) على Vercel، مع قاعدة بيانات Postgres سحابية بدل SQLite. اتبع الخطوات بالترتيب.

## 0) قبل أي شيء: التوكن

- تأكد أنك ألغيت أي توكن قديم مسّرب من BotFather (أمر `/revoke`).
- ضع التوكن الجديد فقط داخل متغيرات بيئة Vercel لاحقاً — لا تكتبه أبداً داخل أي ملف كود أو Git.

## 1) إنشاء قاعدة بيانات Postgres سحابية

اختر واحدة (كلها تعمل مع Vercel بسهولة، مجانية للبدء):
- **Neon** (neon.tech) — الأسهل والأكثر شيوعاً مع Vercel.
- **Vercel Postgres / Vercel Storage → Postgres** — من داخل لوحة تحكم مشروعك على Vercel مباشرة.
- **Supabase** (supabase.com).

أنشئ قاعدة بيانات، وانسخ **Connection String** (يبدأ بـ `postgres://` أو `postgresql://`). سيصبح هذا هو `DATABASE_URL`.

## 2) رفع المشروع إلى GitHub

```bash
cd telegram-bot-vercel
git init
git add .
git commit -m "initial Vercel bot"
git remote add origin <رابط مستودعك على GitHub>
git push -u origin main
```

## 3) ربط المشروع بـ Vercel

- من vercel.com → Add New Project → اختر مستودع GitHub الذي رفعته.
- Vercel سيتعرف تلقائياً على تطبيق Flask (Zero-config Python Runtime) بدون أي إعداد إضافي.

## 4) ضبط متغيرات البيئة على Vercel

من Project Settings → Environment Variables، أضف (انظر `.env.example` للقائمة الكاملة):

| المتغير | القيمة |
|---|---|
| `TELEGRAM_BOT_TOKEN` | توكن البوت من BotFather |
| `ADMIN_IDS` | `8630643080` (أو أكثر من آيدي مفصولة بفواصل) |
| `DATABASE_URL` | connection string من الخطوة 1 |
| `ADMIN_PANEL_TOKEN` | كلمة سر قوية من اختيارك لحماية لوحة الإدارة |
| `WEBHOOK_SECRET` | نص عشوائي قوي (موصى به) |
| `CRON_SECRET` | نص عشوائي قوي لحماية مسار الفحص الدوري |
| باقي المتغيرات الاختيارية | القناة، الدعم، عناوين الإيداع... |

بعد الحفظ، اعمل **Redeploy** حتى تُطبَّق المتغيرات.

## 5) تهيئة قاعدة البيانات لأول مرة

بعد أول نشر ناجح، شغّل تهيئة الجداول مرة واحدة. أسهل طريقة: أضف مسار مؤقت أو نفّذ محلياً:

```bash
pip install -r requirements.txt
export DATABASE_URL="نفس القيمة الموضوعة على Vercel"
python3 -c "from bot import database as db; db.init_db(); print('تم إنشاء الجداول')"
```

## 6) تسجيل Webhook تيليجرام

بعد النشر، رابط تطبيقك سيكون مثل `https://your-app.vercel.app`. سجّل الـ webhook (فعّلها مرة واحدة فقط):

```bash
curl -F "url=https://your-app.vercel.app/api/telegram-webhook" \
     -F "secret_token=<نفس قيمة WEBHOOK_SECRET>" \
     "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook"
```

تحقق من النتيجة:

```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getWebhookInfo"
```

## 7) ⚠️ فحص الرسائل الدورية (الأهم)

في النسخة الأصلية، البوت كان يفحص الرسائل الجديدة تلقائياً كل 15 ثانية عبر عملية مستمرة (job_queue). **Vercel لا يدعم عمليات مستمرة إطلاقاً** — لذلك تم استبدال هذا بمسار HTTP:

```
GET/POST https://your-app.vercel.app/api/cron/check-messages?secret=<CRON_SECRET>
```

يجب استدعاء هذا المسار بشكل دوري من مصدر خارجي. الخيارات:

1. **خدمة كرون خارجية مجانية (موصى بها، تعمل على أي خطة Vercel)** — سجّل في [cron-job.org](https://cron-job.org) مجاناً، وأضف مهمة تستدعي الرابط أعلاه كل دقيقة.
2. **Vercel Cron Jobs** — تعمل فقط إذا كنت على خطة **Pro** (خطة Hobby المجانية تسمح بمرة واحدة في اليوم فقط، غير كافية لبوت أرقام مؤقتة). إذا كنت على Pro، أضف في `vercel.json`:
   ```json
   "crons": [{ "path": "/api/cron/check-messages", "schedule": "* * * * *" }]
   ```
   (وأضف `CRON_SECRET` تحقّقاً إضافياً أو اعتمد فقط على أن Vercel Cron يستدعي من داخل شبكتها).

بدون هذه الخطوة، المستخدمون **لن يستقبلوا إشعارات الرسائل الجديدة تلقائياً** — لكن زر "📥 فحص الرسائل" داخل البوت يفحص لحظياً عند الضغط عليه بأي حال.

## 8) لوحة الإدارة

لوحة الإدارة (`public/index.html`) تعمل على نفس الدومين تلقائياً على `https://your-app.vercel.app/`. تسجيل الدخول يتم بنفس طريقة الأصل (طلب كود OTP يُرسل إلى تيليجرام الأدمن، ثم إدخاله).

## القيود المهمة التي يجب معرفتها

- **لا polling حقيقي** — الفحص الدوري يعتمد على استدعاء خارجي كل دقيقة كحد أدنى عملي، ليس كل 15 ثانية كالأصل.
- **قاعدة بيانات خارجية مطلوبة** — SQLite المحلي لا يعمل على Vercel لأن نظام الملفات مؤقت ويُمسح مع كل طلب.
- **مهلة تنفيذ الدالة** — كل استدعاء (webhook أو كرون) محدود بمهلة زمنية (مضبوطة هنا على 60 ثانية في `vercel.json`، يمكن رفعها حسب خطتك).
- **السكرابر (`scraper.py`)** يعتمد على سحب بيانات من temp-number.com في كل استدعاء — إذا تغيّر شكل الموقع أو حظر الطلبات من عناوين Vercel، يجب تحديث السكرابر.
