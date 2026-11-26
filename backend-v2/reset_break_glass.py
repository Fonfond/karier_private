"""Перевыпуск или блокировка аварийной учётной записи.

    .\\venv\\Scripts\\python reset_break_glass.py            # новые пароль и TOTP
    .\\venv\\Scripts\\python reset_break_glass.py --disable  # заблокировать аккаунт
"""

from __future__ import annotations

import sys

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Employee
from app.services import break_glass as bg
from app.services.break_glass import BREAK_GLASS_TAB


def main() -> int:
    db = SessionLocal()
    try:
        if "--disable" in sys.argv:
            bg.disable(db)
            print()
            print("=" * 66)
            print("  Аварийная учётная запись 000000 заблокирована.")
            print("  Вернуть доступ: python reset_break_glass.py (без флага).")
            print("=" * 66)
            print()
            return 0

        exists = db.scalar(select(Employee).where(Employee.tab_no == BREAK_GLASS_TAB)) is not None
        if not exists:
            print("Аккаунт 000000 не найден — запускаю создание (seed_break_glass.py).")

        data = bg.provision(db, rotate=True)
        qr = bg.ascii_qr(data["otpauth"])
        bar = "=" * 66
        print()
        print(bar)
        print("  ПЕРЕВЫПУСК АВАРИЙНОГО ДОСТУПА")
        print(bar)
        print(f"  Табельный: {data['tab_no']}  ·  роль admin")
        print()
        print(f"  Новый пароль: {data['password']}")
        print(f"  Новый TOTP-секрет: {data['secret']}")
        print()
        print("  QR-код:")
        for line in qr.splitlines():
            print("   " + line)
        print()
        print(bar)
        print("  Старые пароль и код больше не действуют. Распечатайте новый лист,")
        print("  замените конверт в сейфе, старый — уничтожьте.")
        print(bar)
        print()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
