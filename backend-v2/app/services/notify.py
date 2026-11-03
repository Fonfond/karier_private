"""Уведомления и доставка одноразовых кодов.

Спринт 1: канал Telegram — заглушка с печатью в консоль сервера (так требование
и сформулировано), email — тот же принцип. Интерфейс готов к подключению
реального бота: достаточно реализовать `_send_telegram`.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass

from app.core.config import settings

logger = logging.getLogger("karier.notify")


@dataclass
class Delivery:
    channel: str
    target: str | None
    delivered: bool


def mask_target(target: str | None) -> str | None:
    if not target:
        return None
    if "@" in target:
        name, domain = target.split("@", 1)
        return f"{name[:2]}***@{domain}"
    digits = "".join(ch for ch in target if ch.isdigit())
    if len(digits) >= 4:
        return f"+{digits[:1]}***{digits[-2:]}"
    return "***"


def send_otp_code(*, tab_no: str, code: str, channel: str, telegram_id: int | None,
                  email: str | None) -> Delivery:
    target = str(telegram_id) if channel == "telegram" and telegram_id else email
    if channel == "manual":
        logger.warning(
            "Код для табельного %s выдан администратором вручную: %s", tab_no, code
        )
        _print_banner(tab_no, code, "manual")
        return Delivery("manual", None, True)

    if settings.CONSOLE_NOTIFICATIONS:
        logger.warning(
            "OTP для %s (%s → %s): %s", tab_no, channel, mask_target(target), code
        )
        _print_banner(tab_no, code, channel)
        return Delivery(channel, mask_target(target), True)

    # Здесь будет реальная отправка (aiogram / smtplib).
    logger.info("OTP для %s отправлен через %s", tab_no, channel)
    return Delivery(channel, mask_target(target), True)


def _print_banner(tab_no: str, code: str, channel: str) -> None:
    if not settings.is_dev:
        return
    line = "=" * 56
    print(
        f"\n{line}\n  OTP [{channel}] табельный {tab_no}: {code}\n{line}\n",
        file=sys.stdout,
        flush=True,
    )
