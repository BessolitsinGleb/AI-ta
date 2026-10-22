"""Письма: Gmail SMTP с паролем приложения. Без пароля — режим разработки: письмо пишется в лог и в outbox."""
from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from html import escape

from .config import settings

log = logging.getLogger("amba.mail")


@dataclass
class Mail:
    to: str
    subject: str
    text: str
    html: str


outbox: list[Mail] = []  # последние письма в режиме разработки (и в тестах)


def _send_smtp(mail: Mail) -> None:
    msg = EmailMessage()
    msg["From"] = settings.mail_from or settings.smtp_user
    msg["To"] = mail.to
    msg["Subject"] = mail.subject
    msg.set_content(mail.text)
    msg.add_alternative(mail.html, subtype="html")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


async def send(mail: Mail) -> None:
    if not (settings.smtp_user and settings.smtp_password):
        outbox.append(mail)
        del outbox[:-50]
        log.warning("SMTP не настроен — письмо не отправлено.\nКому: %s\nТема: %s\n%s", mail.to, mail.subject, mail.text)
        return
    try:
        await asyncio.to_thread(_send_smtp, mail)
    except Exception:  # письмо не должно ронять регистрацию; пользователь сможет запросить повтор
        log.exception("не удалось отправить письмо на %s", mail.to)


def _layout(title: str, body: str, button: str, url: str) -> str:
    return f"""<!doctype html><html lang="ru"><body style="margin:0;background:#e9eff1;font-family:Arial,Helvetica,sans-serif;color:#0f2d3a">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:32px 12px">
<table role="presentation" width="100%" style="max-width:520px;background:#fff;border-radius:18px;padding:28px">
<tr><td style="font-size:22px;font-weight:700;padding-bottom:8px">🐯 Амба</td></tr>
<tr><td style="font-size:20px;font-weight:700;padding-bottom:12px">{escape(title)}</td></tr>
<tr><td style="font-size:16px;line-height:1.5;color:#3d5a66;padding-bottom:22px">{body}</td></tr>
<tr><td><a href="{escape(url)}" style="display:inline-block;background:#f0641e;color:#fff;text-decoration:none;font-weight:700;padding:14px 22px;border-radius:12px">{escape(button)}</a></td></tr>
<tr><td style="font-size:13px;color:#6b8590;padding-top:22px">Если кнопка не работает, откройте ссылку: <br><a href="{escape(url)}" style="color:#2e6b62;word-break:break-all">{escape(url)}</a><br><br>Если вы не запрашивали это письмо, просто проигнорируйте его.</td></tr>
</table></td></tr></table></body></html>"""


def verify_mail(to: str, name: str, url: str) -> Mail:
    hi = f"{name}, " if name else ""
    return Mail(to, "Подтвердите почту — Амба",
                f"Здравствуйте! {hi}подтвердите почту, чтобы войти в Амбу: {url}\nСсылка действует 24 часа.",
                _layout("Подтвердите почту", f"Здравствуйте! {escape(hi)}осталось подтвердить почту, и можно планировать поездки по Приморью. Ссылка действует 24 часа.", "Подтвердить почту", url))


def reset_mail(to: str, url: str) -> Mail:
    return Mail(to, "Сброс пароля — Амба",
                f"Чтобы задать новый пароль, откройте ссылку: {url}\nСсылка действует 1 час.",
                _layout("Сброс пароля", "Нажмите кнопку, чтобы задать новый пароль. Ссылка действует 1 час и сработает один раз.", "Задать новый пароль", url))
