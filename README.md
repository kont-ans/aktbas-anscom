# بوت الأرقام المؤقتة — نسخة Vercel

نسخة مُحوَّلة من بوت تيليجرام + لوحة إدارة Flask + قاعدة بيانات، للعمل على **Vercel** (Serverless / Webhook) بدل التشغيل المستمر (polling) وبدل SQLite المحلي.

## البنية

```
telegram-bot-vercel/
├── index.py              # نقطة الدخول الموحّدة على Vercel (تطبيق Flask واحد)
├── bot/
│   ├── config.py          # كل الإعدادات، تُقرأ من متغيرات البيئة
│   ├── database.py        # طبقة قاعدة البيانات (PostgreSQL بدل SQLite)
│   ├── handlers.py        # كل منطق البوت (محادثات، أزرار، أدمن...) + دعم Webhook
│   ├── admin_routes.py    # واجهة برمجية لوحة الإدارة (Flask Blueprint)
│   └── scraper.py         # سكرابر temp-number.com (بلا تغيير جوهري)
├── public/
│   └── index.html         # واجهة لوحة الإدارة (تُقدَّم كملف ثابت)
├── requirements.txt
├── vercel.json
├── .env.example
└── DEPLOY.md               # دليل النشر الكامل خطوة بخطوة
```

## أهم الفروقات عن النسخة الأصلية

1. **لا `run_polling`** — البوت يستقبل التحديثات عبر `POST /api/telegram-webhook`.
2. **لا `job_queue`** — الفحص الدوري للرسائل الجديدة صار مساراً منفصلاً `GET/POST /api/cron/check-messages` يجب استدعاؤه من مصدر خارجي كل دقيقة (راجع `DEPLOY.md`، القسم 7).
3. **PostgreSQL بدل SQLite** — عبر `DATABASE_URL`، لأن نظام ملفات Vercel مؤقت.
4. **جلسات/أكواد تسجيل دخول لوحة الإدارة تُخزَّن في قاعدة البيانات** بدل الذاكرة، لأن العمليات الخادمة بلا حالة مشتركة بين الاستدعاءات.

## البدء محلياً (اختياري، للتجربة قبل النشر)

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=...
export DATABASE_URL=postgresql://...
python3 -c "from bot import database as db; db.init_db()"
python3 -c "import index; index.app.run(port=8000)"
```

للنشر الفعلي على Vercel، اتبع `DEPLOY.md`.
