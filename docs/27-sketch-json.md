# JSON-схема по эскизу (karier.sketch/v1)

Файлы:
* `backend-v2/seed_data/sketch_v1.json` — канонический JSON демо-схемы;
* `docs/sketches/sketch-v1.json` — копия для документации;
* `backend-v2/gen_sketch_json.py` — генерация JSON из текущей схемы в БД;
* `backend-v2/import_sketch_json.py` — импорт JSON в схему.

## Формат

```json
{
  "format": "karier.sketch/v1",
  "name": "Схема по эскизу: ПС 35/6 — БКРУ-2 / КТП №4",
  "canvas": { "width": 1024, "height": 576, "units": "m" },
  "library": ["substation_35_6", "bkru_standard", "pole", "recloser", "ktp_standard"],
  "blocks": [
    {
      "id": "b0",
      "block": "substation_35_6",
      "title": "ПС 35/6 кВ «Карьер»",
      "position": { "x": 40, "y": 40 },
      "params": {
        "sections": ["I секция шин 6.3 кВ (яч. 1–15)", "II секция шин 6.3 кВ (яч. 16–30)"],
        "incoming": ["Ввод 1 · ЯКНО-6 №1 (яч. 1)", "Ввод 2 · ЯКНО-6 №2 (яч. 16)"],
        "feeders": [
          { "name": "ф.7к", "cable": "СБ-3×185" },
          { "name": "ф.16к", "cable": "СБ-3×95" }
        ],
        "section_breaker": "СВ · секционный выключатель (яч. 8/23)",
        "equipment": ["ТТ 6 кВ", "ОПН 6 кВ", "ЗНВ-6"]
      },
      "ports": [
        { "code": "IN-1", "kind": "in", "label": "Ввод 1", "voltage_kv": 6.0 },
        { "code": "OUT-1", "kind": "out", "label": "ф.7к", "voltage_kv": 6.0 }
      ]
    }
  ],
  "links": [
    {
      "id": "…uuid…",
      "from": { "block": "b0", "port": "OUT-1" },
      "to": { "block": "b2", "port": "IN-1" },
      "type": "cable",
      "cable_mark": "СБ-3×185",
      "length_m": 120,
      "state": "connected"
    }
  ]
}
```

## Состав схемы

| id | блок | подпись | позиция |
|---|---|---|---|
| b0 | `substation_35_6` | ПС 35/6 кВ «Карьер» | 40, 40 |
| b1 | `bkru_standard` | БКРУ-2 | 320, 320 |
| b2 | `recloser` | Реклоузер | 320, 40 |
| b3 | `yakno` | ЯКНО-1 | 620, 340 |
| b4 | `pole` | оп.14 | 470, 40 |
| b5 | `pole` | оп.13 | 600, 40 |
| b6 | `pole` | оп.12 | 730, 40 |
| b7 | `ktp_standard` | КТП №4 | 860, 40 |

Связи: ПС.ф.7к → Реклоузер → оп.14 → оп.13 → оп.12 → КТП №4 (СИП-3 3×120/3×70);
ПС.ф.16к → БКРУ-2 → ЯКНО-1 (СБ-3×95, СБ-3×70).

## Импорт

```powershell
cd backend-v2
.\\venv\\Scripts\\python import_sketch_json.py seed_data/sketch_v1.json --dry-run
.\\venv\\Scripts\\python import_sketch_json.py seed_data/sketch_v1.json --clean
```

`--dry-run` проверяет шаблоны, координаты и связи без записи в БД.
`--clean` удаляет предыдущий импорт (метка `attrs.demo = "json:karier.sketch/v1"`).
Импорт создаёт реальные объекты через библиотеку блоков, затем связи через порты.

## Проверки

* `import_sketch_json.py --dry-run` — 8 блоков, 7 связей, шаблоны и координаты валидны;
* реальный импорт — 8 блоков, 7 связей, затем демо восстановлено;
* `pytest` — **113 passed**.
