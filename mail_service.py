import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional

from config import (
    MAIL_FROM_ADDRESS,
    MAIL_FROM_NAME,
    MAIL_MODE,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USERNAME,
    SMTP_USE_TLS,
)


logger = logging.getLogger(__name__)


def mask_email(value: Optional[str]) -> str:
    text = (value or "").strip()
    if "@" not in text:
        return "***"
    local, domain = text.split("@", 1)
    if not local:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"


def mask_url(value: Optional[str]) -> str:
    text = (value or "").strip()
    if text.startswith("https://"):
        return "https://***"
    if text.startswith("http://"):
        return "http://***"
    return "***"


@dataclass
class DeliveryResult:
    ok: bool
    status: str
    error_code: Optional[str] = None
    error_message: Optional[str] = None


def build_delivery_body(
    *,
    display_name: str,
    product_name: str,
    download_url: str,
    download_password: Optional[str],
    file_size_label: Optional[str],
    order_id: str,
) -> str:
    password_text = download_password or "なし"
    size_text = file_size_label or "未設定"
    return (
        f"{display_name} 様\n\n"
        f"「{product_name}」をご購入いただき、ありがとうございます。\n\n"
        "ダウンロードURL：\n"
        f"{download_url}\n\n"
        "解凍パスワード：\n"
        f"{password_text}\n\n"
        f"ファイルサイズ：{size_text}\n"
        f"注文番号：{order_id}\n\n"
        "本URL、パスワードおよびコンテンツを第三者へ共有・転載しないでください。\n"
        "リンクが利用できない場合は、Discord の「私の写真集」から最新情報をご確認ください。\n\n"
        "Kiri Club\n"
    )


def send_delivery_email(
    *,
    to_email: str,
    display_name: str,
    product_name: str,
    download_url: str,
    download_password: Optional[str],
    file_size_label: Optional[str],
    order_id: str,
) -> DeliveryResult:
    masked = mask_email(to_email)
    subject = f"【Kiri Club】写真集下载信息：{product_name}"

    if MAIL_MODE != "smtp":
        logger.info("delivery mail simulated order_id=%s to=%s url=%s", order_id, masked, mask_url(download_url))
        return DeliveryResult(ok=True, status="SIMULATED")

    if not SMTP_HOST or not MAIL_FROM_ADDRESS:
        return DeliveryResult(ok=False, status="FAILED", error_code="SMTP_CONFIG", error_message="SMTP is not configured")

    body = build_delivery_body(
        display_name=display_name,
        product_name=product_name,
        download_url=download_url,
        download_password=download_password,
        file_size_label=file_size_label,
        order_id=order_id,
    )
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{MAIL_FROM_NAME} <{MAIL_FROM_ADDRESS}>"
    msg["To"] = to_email
    msg.set_content(body)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as smtp:
            if SMTP_USE_TLS:
                smtp.starttls()
            if SMTP_USERNAME:
                smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
            smtp.send_message(msg)
        logger.info("delivery mail sent order_id=%s to=%s", order_id, masked)
        return DeliveryResult(ok=True, status="SENT")
    except Exception as exc:
        logger.warning("delivery mail failed order_id=%s to=%s error=%s", order_id, masked, exc)
        return DeliveryResult(ok=False, status="FAILED", error_code=exc.__class__.__name__, error_message=str(exc)[:300])
