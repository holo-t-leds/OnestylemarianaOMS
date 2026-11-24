"""
Servicio de correo transaccional con respaldo seguro en consola local.
No expone tokens en respuestas HTTP (OWASP A07 / RF-SEG-016).
"""
import logging
import os
import smtplib
from email.message import EmailMessage

logger = logging.getLogger("onestyle.mailer")


def send_password_recovery_email(recipient_email: str, token: str, ttl_minutes: int = 60) -> str:
    """
    Envía instrucciones de restablecimiento de contraseña usando SMTP si está configurado en .env.
    Si faltan variables SMTP (entorno local), registra el token únicamente en la consola/logger del servidor.
    """
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587") or 587)
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_pass = (os.getenv("SMTP_PASS") or os.getenv("SMTP_PASSWORD") or "").strip()
    smtp_from = (os.getenv("SMTP_FROM") or smtp_user or "no-reply@onestylemariana.co").strip()
    base_url = os.getenv("APP_BASE_URL", "http://127.0.0.1:5000").rstrip("/")

    reset_url = f"{base_url}/#/cuenta?reset_token={token}"
    body_text = (
        "Hola,\n\n"
        "Recibimos una solicitud para restablecer tu contraseña en OneStyleMariana.\n"
        f"Tu código de recuperación (válido por {ttl_minutes} minutos, un solo uso) es:\n\n"
        f"    {token}\n\n"
        f"También puedes ingresar desde: {reset_url}\n\n"
        "Si no solicitaste este cambio, puedes ignorar este mensaje con tranquilidad."
    )

    if not (smtp_host and smtp_user and smtp_pass):
        msg_console = (
            f"[DEV RECOVERY EMAIL] Destinatario={recipient_email} | "
            f"TTL={ttl_minutes}min | Token={token}"
        )
        logger.info(msg_console)
        print(msg_console, flush=True)
        return "console"

    email_msg = EmailMessage()
    email_msg["Subject"] = "OneStyleMariana — Recuperación de contraseña"
    email_msg["From"] = smtp_from
    email_msg["To"] = recipient_email
    email_msg.set_content(body_text)

    if smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10) as server:
            server.login(smtp_user, smtp_pass)
            server.send_message(email_msg)
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.send_message(email_msg)

    return "smtp"
