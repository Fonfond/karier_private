"""Идемпотентное наполнение модели оборудования «Карьер» (этап 1).

Зачем отдельный модуль: миграция 0015 размечает данные, существующие на момент
``alembic upgrade``. Тестовая БД собирается иначе — сначала миграции на пустой
схеме, затем перезалив демо-дампа (``.local/reset-test-db.ps1``): строки типов
появляются уже после мигратора, а ``equipment_class`` получает server_default
``equipment``. Этот модуль добивает модель по уже загруженным данным:

* классы оборудования и вкладки (``equipment_class``/``group_code``);
* тип ``cable`` с кабельным ``lifecycle_status``;
* поля паспорта ``gis.asset_type_fields`` из ``attr_schema``/``required_attrs``;
* колонки ячеек/кабеля из ``schema_role`` и ``attrs``.

Запуск из backend-v2 (рабочую БД не трогать — DSN берётся из окружения):

    python -m app.seed_equipment_model

Повторный запуск безопасен: обновляются только недостающие значения.
"""

from __future__ import annotations

import sys

from app.db.session import SessionLocal
from app.services import asset_fields
from app.services import equipment_templates


def apply() -> dict[str, int]:
    db = SessionLocal()
    try:
        counts = asset_fields.backfill_equipment_model(db)
        # Этап 2: шаблоны БКРУ/ПС/КТП и тип «Разъединитель» — идемпотентно и
        # только для типов без v2-шаблона (правки админа не перезаписываются).
        counts.update(equipment_templates.seed_type_templates(db))
        db.commit()
        return counts
    finally:
        db.close()


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - поток может быть уже перенаправлен
            pass

    counts = apply()
    print("Модель оборудования добрана:")
    print(f"  классов размечено        : {counts.get('classes', 0)}")
    print(f"  вкладок (group_code)     : {counts.get('group_codes', 0)}")
    print(f"  полей типов добавлено    : {counts.get('type_fields', 0)}")
    print(f"  ячеек: cell_kind         : {counts.get('assets_cell_kind', 0)}")
    print(f"  ячеек: cell_no           : {counts.get('assets_cell_no', 0) + counts.get('assets_cell_no_attr', 0)}")
    print(
        "  секций: section_no       : "
        f"{counts.get('assets_section_no', 0) + counts.get('assets_section_no_attr', 0)}"
    )
    print(
        "  кабелей: lifecycle_status: "
        f"{counts.get('assets_cable_reserve', 0) + counts.get('assets_cable_status_attr', 0) + counts.get('assets_cable_default', 0)}"
    )
    print(f"  шаблонов БКРУ/ПС/КТП     : {counts.get('templates', 0)}")
    print(f"  тип «Разъединитель»      : {counts.get('disconnector_type', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
