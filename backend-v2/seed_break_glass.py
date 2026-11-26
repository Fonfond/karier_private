"""Создание аварийной учётной записи (break glass).

Запуск из backend-v2:
    .\\venv\\Scripts\\python seed_break_glass.py

Скрипт печатает пароль, TOTP-секрет и ASCII QR-код. Их нужно распечатать,
запечатать в конверт и хранить в сейфе. Повторный запуск перевыпускает секреты
(старые перестают действовать).
"""

from __future__ import annotations

import sys
import textwrap

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Employee
from app.services import break_glass as bg
from app.services.break_glass import BREAK_GLASS_TAB


def main() -> int:
    db = SessionLocal()
    try:
        exists = db.scalar(select(Employee).where(Employee.tab_no == BREAK_GLASS_TAB)) is not None
        data = bg.provision(db, rotate=exists)

        qr = bg.ascii_qr(data["otpauth"])
        bar = "=" * 66
        print()
        print(bar)
        print("  АВАРИЙНЫЙ ДОСТУП (BREAK GLASS)")
        print(bar)
        print(f"  {'Перевыпущен' if exists else 'Создан'} аккаунт: табельный {data['tab_no']}  ·  роль admin")
        print()
        print("  ПАРОЛЬ:")
        print(f"    {data['password']}")
        print()
        print("  TOTP-СЕКРЕТ (вводится в Google Authenticator / Aegis вручную):")
        print(f"    {data['secret']}")
        print()
        print("  Ссылка для приложения:")
        print(textwrap.fill(data["otpauth"], width=62, initial_indent="    ", subsequent_indent="    "))
        print()
        print("  QR-КОД (наведите камеру):")
        for line in qr.splitlines():
            print("   " + line)
        print()
        print(bar)
        print("  ЧТО ДЕЛАТЬ ДАЛЬШЕ")
        print(bar)
        print("  1. Распечатайте этот лист (пароль + секрет + QR).")
        print("  2. Запечатайте в конверт, подпишите и положите в сейф.")
        print("  3. Второй экземпляр — у главного энергетика / директора.")
        print("  4. Не храните файл на компьютере и не пересылайте в мессенджерах.")
        print("  5. После использования — перевыпустите: python reset_break_glass.py.")
        print(bar)
        print("  Вход: табельный 000000 → пароль → код из приложения.")
        print("  Все действия этого аккаунта помечаются в журнале: break_glass = true.")
        print(bar)
        print()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
