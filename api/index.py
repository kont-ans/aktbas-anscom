"""
نقطة الدخول الموحّدة على Vercel.
موجودة داخل api/ لأن Vercel Python runtime يبحث عن الدوال المُصرَّح عنها
في vercel.json داخل مجلد api/ فقط. نضيف جذر المشروع إلى sys.path
حتى تعمل "from bot import ..." بشكل صحيح من هذا الموقع.
Vercel يبحث عن كائن Flask اسمه `app` في هذا الملف (zero-config Python runtime)
ويوجّه له كل الطلبات التي لا تطابق ملفاً ثابتاً داخل public/.
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, jsonify

from bot import config
from bot.handlers import process_update, get_application, check_active_session
from bot.admin_routes import admin_bp
from bot import database as db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("index")

app = Flask(__name__)
app.register_blueprint(admin_bp)


@app.route("/api/telegram-webhook", methods=["POST"])
def telegram_webhook():
    """يستقبل تحديثات تيليجرام (webhook) بدل الـ polling."""
    if config.WEBHOOK_SECRET:
        got = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if got != config.WEBHOOK_SECRET:
            return jsonify({"error": "unauthorized"}), 401

    update_dict = request.get_json(force=True, silent=True) or {}
    try:
        asyncio.run(process_update(update_dict))
    except Exception:
        logger.exception("فشل معالجة تحديث تيليجرام")
    # نرد دوماً بـ 200 حتى لا يعيد تيليجرام إرسال نفس التحديث بلا نهاية
    return jsonify({"ok": True})


@app.route("/api/cron/check-messages", methods=["GET", "POST"])
def cron_check_messages():
    """
    يستبدل job_queue القديم: يفحص كل الأرقام النشطة لجميع المستخدمين
    ويرسل أي رسائل جديدة. يجب استدعاء هذا المسار بشكل دوري من خدمة
    خارجية (cron-job.org) أو Vercel Cron (خطة Pro). راجع DEPLOY.md.
    """
    if config.CRON_SECRET:
        got = request.headers.get("X-Cron-Secret") or request.args.get("secret", "")
        if got != config.CRON_SECRET:
            return jsonify({"error": "unauthorized"}), 401

    async def _run():
        application = await get_application()
        sessions = db.list_active_numbers()
        checked = 0
        errors = 0
        for session in sessions:
            try:
                await check_active_session(application.bot, session)
                checked += 1
            except Exception:
                errors += 1
                logger.exception("فشل فحص الجلسة %s", session.get("id"))
        return checked, errors

    checked, errors = asyncio.run(_run())
    return jsonify({"ok": True, "checked": checked, "errors": errors})
