"""Уведомления и доставка одноразовых кодов.

Спринт 1: канал Telegram — заглушка с печатью в консоль сервера (так требование
и сформулировано), email — тот же принцип. Интерфейс готов к подключению
реального бота: достаточно реализовать `_send_telegram`.

S-5: код ОТСУТСТВУЕТ в логах и в stdout. Раньше `send_otp_code` писал 6-значный
код в logger.warning и в баннер — это утечка (журнал читают все, у кого есть
доступ к серверу). Теперь код первичной регистрации выдаётся администратору
через API (POST /api/employees/{id}/otp), а логи содержат только канал и маску
адреса получателя.
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


def send_otp_code(
    *,
    tab_no: str,
    code: str,
    channel: str,
    telegram_id: int | None,
    email: str | None,
) -> Delivery:
    """Доставить код сотруднику.

    `code` принимается для совместимости вызовов, но НИКОГДА не попадает ни в лог,
    ни в stdout (S-5). Для канала `manual` код вообще не доставляется сервером —
    его передаёт администратор.
    """
    del code  # осознанно не используем: код не должен попасть в журнал

    target = str(telegram_id) if channel == "telegram" and telegram_id else email
    masked = mask_target(target)

    if channel == "manual":
        logger.info("Код первичной регистрации для %s выдан администратором", tab_no)
        _print_banner(tab_no, "manual")
        return Delivery("manual", None, True)

    if settings.CONSOLE_NOTIFICATIONS:
        logger.info(
            "OTP для %s (%s → %s) отправлен; код в журнал не пишется",
            tab_no,
            channel,
            masked,
        )
        _print_banner(tab_no, channel)
        return Delivery(channel, masked, True)

    # Здесь будет реальная отправка (aiogram / smtplib).
    logger.info("OTP для %s отправлен через %s", tab_no, channel)
    return Delivery(channel, masked, True)


def _print_banner(tab_no: str, channel: str) -> None:
    """Баннер в консоль стенда: без кода (S-5), только факт выдачи."""
    if not settings.is_dev:
        return
    line = "=" * 56
    print(
        f"\n{line}\n"
        f"  OTP [{channel}] табельный {tab_no}: код выдан\n"
        f"  Код не печатается: его показывает администратор в интерфейсе\n"
        f"{line}\n",
        file=sys.stdout,
        flush=True,
    )
