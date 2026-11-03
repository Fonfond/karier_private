"""UUID v7 — время-упорядоченные идентификаторы (RFC 9562).

Нужны для того, чтобы первичные ключи не фрагментировали b-tree индексы
и сортировались по времени создания без отдельного поля.
"""

from __future__ import annotations

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    """Вернуть UUID v7: 48 бит миллисекунд + 74 бита случайности."""
    ts_ms = int(time.time() * 1000)
    rand = int.from_bytes(os.urandom(10), "big")

    # 48 бит времени
    value = (ts_ms & 0xFFFFFFFFFFFF) << 80
    # 4 бита версии (7)
    value |= 0x7 << 76
    # 12 бит rand_a
    value |= (rand >> 68) & 0x0FFF
    # 2 бита варианта (10)
    value |= 0b10 << 62
    # 62 бита rand_b
    value |= rand & 0x3FFFFFFFFFFFFFFF

    return uuid.UUID(int=value)


def uuid7_str() -> str:
    return str(uuid7())
