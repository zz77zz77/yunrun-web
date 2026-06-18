import os
import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from dotenv import load_dotenv
from loguru import logger


def _activity_info_rows(activity: dict) -> str:
    """生成活动信息 HTML 行，activity 可为空 dict"""
    if not activity:
        return ""
    rows = []
    fields = [
        ("活动名称", activity.get("title") or activity.get("name")),
        ("活动分类", activity.get("category") or activity.get("categoryName")),
        ("活动地址", activity.get("address")),
        ("开始时间", activity.get("start_time") or activity.get("startTime")),
        ("结束时间", activity.get("end_time") or activity.get("endTime")),
        ("报名截止", activity.get("join_end_time") or activity.get("joinEndTime")),
        ("分数/学时", activity.get("credit")),
    ]
    for label, val in fields:
        if val is not None and str(val).strip():
            rows.append(f"<tr><td style='padding:4px 12px 4px 0;color:#555'>{label}</td>"
                        f"<td style='padding:4px 0'><b>{val}</b></td></tr>")
    return f"<table style='border-collapse:collapse'>{''.join(rows)}</table>" if rows else ""


def make_success_email(activity_id: str, user: dict, activity: dict = None, msg: str = "") -> str:
    info = _activity_info_rows(activity or {})
    msg_row = f"<p style='color:#888'>服务器消息：{msg}</p>" if msg else ""
    return (
        "<html><head><meta charset='utf-8'></head><body style='font-family:sans-serif'>"
        "<h3 style='color:#2e7d32'>✅ 报名成功通知</h3>"
        f"<p>用户：<b>{user.get('userName','')}</b></p>"
        f"{info}"
        f"<p style='color:#888;font-size:12px'>活动ID：{activity_id}</p>"
        f"{msg_row}"
        "</body></html>"
    )


def make_fail_email(activity_id: str, user: dict, activity: dict = None, msg: str = "") -> str:
    info = _activity_info_rows(activity or {})
    msg_row = f"<p style='color:#c62828'>失败原因：{msg}</p>" if msg else ""
    return (
        "<html><head><meta charset='utf-8'></head><body style='font-family:sans-serif'>"
        "<h3 style='color:#c62828'>❌ 报名失败通知</h3>"
        f"<p>用户：<b>{user.get('userName','')}</b></p>"
        f"{info}"
        f"<p style='color:#888;font-size:12px'>活动ID：{activity_id}</p>"
        f"{msg_row}"
        "<p>本次报名未成功，请关注后续活动。</p>"
        "</body></html>"
    )


def send_email(email_info: str, addressee: str) -> bool:
    load_dotenv()
    try:
        smtp_server = os.getenv("INFO_EMAIL_SERVER")
        smtp_port = int(os.getenv("INFO_EMAIL_PORT", "465"))
        sender_email = os.getenv("INFO_EMAIL_HOST", "").strip('"')
        sender_password = os.getenv("INFO_EMAIL_SMTP_PASS", "").strip('"')

        if not sender_email or not sender_password or not smtp_server:
            logger.warning("邮件配置不完整，跳过发送")
            return False
        if not addressee or not addressee.strip():
            logger.warning("收件人邮箱为空，跳过发送")
            return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = Header("PU 活动通知", "utf-8")
        msg["From"] = formataddr(("PU活动助手", sender_email))
        msg["To"] = formataddr(("你", addressee))
        msg.attach(MIMEText(email_info, "html", "utf-8"))

        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg)
        logger.success(f"邮件发送成功: {addressee}")
        return True
    except Exception as e:
        logger.error(f"邮件发送失败: {e}")
        return False
