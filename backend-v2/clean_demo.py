"""Сброс демонстрационных данных перед показом.

Запуск из backend-v2:
    .\\venv\\Scripts\\python clean_demo.py            # удалить демо-дефекты, обходы, тестовых сотрудников
    .\\venv\\Scripts\\python clean_demo.py --dry-run  # только показать, что будет удалено
    .\\venv\\Scripts\\python clean_demo.py --photos   # дополнительно удалить демо-фото

Учётная запись 000001 (администратор) и реальный справочник не затрагиваются.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import func, or_, select

from app.db.session import SessionLocal
from app.models import AssetMove, Defect, Employee, Inspection, Media

DEMO_PREFIX = "ДЕМО:%"
DEMO_INSPECTION = "Плановый обход: северный борт"
KEEP_TABS = ("000001", "000002", "000003", "000004")
TEST_NAMES = ("Регистров%", "Тестов%", "Проверкин%", "Удаляев%", "Наблюдатель%")


def main() -> int:
    parser = argparse.ArgumentParser(description="Очистка демо-данных карьера")
    parser.add_argument("--dry-run", action="store_true", help="показать без удаления")
    parser.add_argument("--photos", action="store_true", help="удалить и демо-фото")
    parser.add_argument("--moves", action="store_true", help="удалить историю перемещений")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        demo_defects = list(
            db.scalars(select(Defect).where(Defect.description.like(DEMO_PREFIX))).all()
        )
        demo_inspections = list(
            db.scalars(select(Inspection).where(Inspection.title == DEMO_INSPECTION)).all()
        )
        test_employees = list(
            db.scalars(
                select(Employee).where(
                    Employee.tab_no.not_in(KEEP_TABS),
                    or_(*[Employee.full_name.like(name) for name in TEST_NAMES]),
                )
            ).all()
        )

        print("=" * 64)
        print("  Очистка демо-данных", "(режим проверки)" if args.dry_run else "")
        print("=" * 64)
        print(f"  демо-дефектов:      {len(demo_defects)}")
        print(f"  демо-обходов:       {len(demo_inspections)}")
        print(f"  тестовых сотрудников: {len(test_employees)}")

        if args.dry_run:
            for defect in demo_defects:
                print(f"    дефект: {defect.description[:60]}")
            for employee in test_employees:
                print(f"    сотрудник: {employee.tab_no} {employee.full_name}")
            print("=" * 64)
            return 0

        for defect in demo_defects:
            db.delete(defect)

        removed_inspections = 0
        for inspection in demo_inspections:
            db.delete(inspection)
            removed_inspections += 1

        removed_employees = 0
        for employee in test_employees:
            db.delete(employee)
            removed_employees += 1

        removed_moves = 0
        if args.moves:
            removed_moves = (
                db.query(AssetMove).filter(AssetMove.note.like("%офлайн%")).delete(
                    synchronize_session=False
                )
            )

        removed_media = 0
        if args.photos:
            demo_media = list(
                db.scalars(select(Media).where(Media.purpose.in_(("inspection", "move_proof")))).all()
            )
            for media in demo_media:
                db.delete(media)
                removed_media += 1

        db.commit()

        remaining_defects = db.scalar(select(func.count(Defect.id))) or 0
        print(f"  удалено: дефектов {len(demo_defects)}, обходов {removed_inspections}, "
              f"сотрудников {removed_employees}, перемещений {removed_moves}, фото {removed_media}")
        print(f"  осталось дефектов в базе: {remaining_defects}")
        print("=" * 64)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
