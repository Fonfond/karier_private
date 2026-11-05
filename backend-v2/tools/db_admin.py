"""Локальная браузерная панель базы данных карьера.

Запуск из backend-v2:
    .\\venv\\Scripts\\python tools\\db_admin.py

Открывается на http://127.0.0.1:8010/?token=... — токен печатается при старте.

Безопасность:
  * слушает только 127.0.0.1;
  * нужен токен (cookie после первого перехода по ссылке);
  * DDL (DROP/ALTER/TRUNCATE и т.п.) запрещён всегда;
  * изменения выполняются в два шага: «Проверить» (ROLLBACK) и «Применить» (COMMIT);
  * значения password_hash/token/secret в предпросмотре маскируются.
"""

from __future__ import annotations

import csv
import io
import os
import re
import secrets
import sys
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel
from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402

PORT = int(os.environ.get("DB_ADMIN_PORT", "8010"))
TOKEN = os.environ.get("DB_ADMIN_TOKEN") or secrets.token_urlsafe(18)
MASK_MARKERS = ("password", "hash", "secret", "token")
FORBIDDEN = re.compile(
    r"^\s*(drop|alter|truncate|create|grant|revoke|vacuum|reindex|cluster|comment|security)\b",
    re.IGNORECASE,
)
ALLOWED_WRITE = re.compile(r"^\s*(insert|update|delete|with)\b", re.IGNORECASE)

app = FastAPI(title="Karier DB Admin", docs_url=None, redoc_url=None, openapi_url=None)


def dsn() -> str:
    return settings.DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")


def connect():
    return psycopg.connect(dsn(), autocommit=False)


def check_token(request: Request) -> None:
    supplied = request.cookies.get("dbadmin_token") or request.query_params.get("token")
    if not supplied or not secrets.compare_digest(supplied, TOKEN):
        raise HTTPException(status_code=401, detail="Нужен токен доступа")


def mask(key: str, value):
    if value is None:
        return None
    if any(marker in key.lower() for marker in MASK_MARKERS) and isinstance(value, str):
        return value[:12] + "…" if len(value) > 12 else "…"
    return value


def jsonable(value):
    if value is None or isinstance(value, (int, float, bool, str)):
        return value
    return str(value)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    supplied = request.cookies.get("dbadmin_token") or request.query_params.get("token")
    if not supplied or not secrets.compare_digest(supplied, TOKEN):
        return HTMLResponse(
            "<h1 style='font-family:sans-serif'>Нужен токен</h1>"
            "<p style='font-family:sans-serif'>Откройте ссылку, которую напечатал скрипт при запуске.</p>",
            status_code=401,
        )
    response = HTMLResponse(PAGE)
    response.set_cookie("dbadmin_token", TOKEN, httponly=True, samesite="strict")
    return response


@app.get("/api/tables")
def tables(request: Request):
    check_token(request)
    query = """
        select c.table_schema as schema, c.table_name as name
        from information_schema.tables c
        where c.table_schema in ('gis', 'ops', 'auth', 'audit', 'public')
          and c.table_type = 'BASE TABLE'
        order by c.table_schema, c.table_name
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(query)
        names = cur.fetchall()

        rows = []
        for schema, name in names:
            cur.execute(
                sql.SQL("select count(*) from {}.{}").format(
                    sql.Identifier(schema), sql.Identifier(name)
                )
            )
            rows.append({"schema": schema, "name": name, "rows": int(cur.fetchone()[0])})

        cur.execute("select current_database(), version()")
        database, version = cur.fetchone()
    return {"database": database, "version": version, "tables": rows}


@app.get("/api/table")
def table_rows(
    request: Request,
    schema: str,
    table: str,
    limit: int = 50,
    offset: int = 0,
    q: str = "",
):
    check_token(request)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "select column_name, data_type from information_schema.columns "
                "where table_schema = %s and table_name = %s order by ordinal_position"
            ),
            (schema, table),
        )
        columns = cur.fetchall()
        if not columns:
            raise HTTPException(status_code=404, detail="Таблица не найдена")

        searchable = [name for name, kind in columns if kind in ("text", "character varying", "uuid")]
        where = sql.SQL("")
        params: list = []
        if q and searchable:
            conditions = []
            for name in searchable:
                conditions.append(sql.SQL("{}::text ilike %s").format(sql.Identifier(name)))
                params.append(f"%{q}%")
            where = sql.SQL(" where (") + sql.SQL(" or ").join(conditions) + sql.SQL(")")

        cur.execute(
            sql.SQL("select count(*) from {}.{}").format(sql.Identifier(schema), sql.Identifier(table))
            + where,
            params,
        )
        total = cur.fetchone()[0]

        cur.execute(
            sql.SQL("select * from {}.{}").format(sql.Identifier(schema), sql.Identifier(table))
            + where
            + sql.SQL(" limit %s offset %s"),
            [*params, limit, offset],
        )
        names = [description.name for description in cur.description]
        data = [
            [mask(name, jsonable(value)) for name, value in zip(names, row)]
            for row in cur.fetchall()
        ]

    return {
        "columns": [{"name": name, "type": kind} for name, kind in columns],
        "rows": data,
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/export")
def export_csv(request: Request, schema: str, table: str, q: str = ""):
    check_token(request)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL("select * from {}.{}").format(sql.Identifier(schema), sql.Identifier(table))
        )
        names = [description.name for description in cur.description]
        rows = cur.fetchall()

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(names)
    writer.writerows(rows)
    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{schema}.{table}.csv"'},
    )


class SqlIn(BaseModel):
    sql: str
    apply: bool = False


@app.post("/api/sql")
def run_sql(payload: SqlIn, request: Request):
    check_token(request)
    statement = payload.sql.strip().rstrip(";")
    if not statement:
        raise HTTPException(status_code=422, detail="Пустой запрос")
    if FORBIDDEN.match(statement):
        raise HTTPException(status_code=403, detail="DDL запрещён: только SELECT/INSERT/UPDATE/DELETE")
    if payload.apply and not (statement.lower().startswith("select") or ALLOWED_WRITE.match(statement)):
        raise HTTPException(status_code=403, detail="Недопустимая операция")

    with connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(statement)
            columns = [description.name for description in (cur.description or [])]
            rows = []
            if columns:
                rows = [
                    [mask(name, jsonable(value)) for name, value in zip(columns, row)]
                    for row in cur.fetchall()
                ]
            affected = cur.rowcount
            if payload.apply:
                conn.commit()
                mode = "applied"
            else:
                conn.rollback()
                mode = "preview"
        except psycopg.Error as exc:
            conn.rollback()
            raise HTTPException(status_code=400, detail=str(exc).strip()) from exc

    return {
        "mode": mode,
        "columns": columns,
        "rows": rows,
        "affected": affected if affected is not None and affected >= 0 else 0,
        "message": (
            "Изменения применены и зафиксированы"
            if payload.apply
            else "Проверка выполнена, изменения откатаны (ROLLBACK)"
        ),
    }


PAGE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8" />
<title>Карьер · База данных</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  :root { color-scheme: dark; --bg:#0b1014; --surface:#111820; --surface2:#16202a; --line:#233040;
          --ink:#e6edf3; --ink2:#9fb0c0; --ink3:#6b7a8a; --accent:#4c9aff; --ok:#2fbf71; --warn:#f5a524; --bad:#f2545b; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink); font:14px/1.45 -apple-system,Segoe UI,Roboto,sans-serif; }
  header { display:flex; align-items:center; gap:12px; padding:10px 16px; border-bottom:1px solid var(--line); background:var(--surface); }
  header b { font-size:15px; }
  header .meta { color:var(--ink3); font-size:12px; }
  .wrap { display:grid; grid-template-columns:260px 1fr; height:calc(100vh - 53px); }
  aside { border-right:1px solid var(--line); overflow:auto; padding:8px; background:var(--surface); }
  aside h3 { margin:12px 8px 4px; font-size:11px; letter-spacing:.06em; text-transform:uppercase; color:var(--ink3); }
  .tbl { display:flex; justify-content:space-between; gap:6px; padding:5px 8px; border-radius:8px; cursor:pointer; color:var(--ink2); font-size:13px; }
  .tbl:hover { background:var(--surface2); color:var(--ink); }
  .tbl.active { background:#1b2a3a; color:var(--ink); }
  .tbl span:last-child { color:var(--ink3); font-size:11px; }
  main { display:flex; flex-direction:column; min-width:0; }
  .bar { display:flex; flex-wrap:wrap; gap:8px; align-items:center; padding:10px 14px; border-bottom:1px solid var(--line); }
  input[type=text], textarea { background:var(--surface2); color:var(--ink); border:1px solid var(--line); border-radius:8px; padding:7px 10px; font:inherit; }
  textarea { width:100%; min-height:84px; font-family:ui-monospace,Consolas,monospace; font-size:12.5px; }
  button { background:var(--surface2); color:var(--ink); border:1px solid var(--line); border-radius:8px; padding:7px 12px; cursor:pointer; font:inherit; }
  button:hover { border-color:#31465f; }
  button.primary { background:var(--accent); border-color:var(--accent); color:#06111f; font-weight:600; }
  button.danger { background:#3a1c1f; border-color:#5c2a2f; color:#ffb3b8; }
  button:disabled { opacity:.5; cursor:default; }
  .content { overflow:auto; flex:1; }
  table { border-collapse:collapse; width:100%; font-size:12.5px; }
  th, td { text-align:left; padding:6px 10px; border-bottom:1px solid var(--line); white-space:nowrap; max-width:340px; overflow:hidden; text-overflow:ellipsis; }
  th { position:sticky; top:0; background:var(--surface); color:var(--ink3); font-weight:600; z-index:1; }
  td.null { color:var(--ink3); font-style:italic; }
  .sqlbox { border-top:1px solid var(--line); padding:10px 14px; background:var(--surface); }
  .row { display:flex; gap:8px; align-items:center; margin-top:8px; flex-wrap:wrap; }
  .status { font-size:12px; color:var(--ink2); }
  .status.ok { color:var(--ok); } .status.bad { color:var(--bad); } .status.warn { color:var(--warn); }
  .pill { font-size:11px; color:var(--ink3); border:1px solid var(--line); border-radius:999px; padding:2px 8px; }
  .empty { padding:24px; color:var(--ink3); }
</style>
</head>
<body>
<header>
  <b>Карьер · База данных</b>
  <span class="meta" id="meta">подключение…</span>
  <span style="flex:1"></span>
  <span class="pill">только 127.0.0.1</span>
  <span class="pill">DDL запрещён</span>
</header>
<div class="wrap">
  <aside id="tree"></aside>
  <main>
    <div class="bar">
      <input type="text" id="q" placeholder="Поиск по таблице…" style="min-width:220px" />
      <button id="search">Найти</button>
      <button id="refresh">Обновить</button>
      <span style="flex:1"></span>
      <span class="status" id="info"></span>
    </div>
    <div class="content" id="rows"><div class="empty">Выберите таблицу слева</div></div>
    <div class="sqlbox">
      <textarea id="sql" placeholder="select * from ops.defects order by detected_at desc limit 20;"></textarea>
      <div class="row">
        <button id="preview">Проверить (без изменений)</button>
        <button class="primary" id="apply">Применить</button>
        <button class="danger" id="delete">Удалить по запросу</button>
        <span class="status" id="sqlStatus"></span>
      </div>
    </div>
  </main>
</div>
<script>
const state = { schema: null, table: null, offset: 0, q: "" };
const $ = (id) => document.getElementById(id);

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || response.statusText);
  }
  return response.json();
}

function cell(value) {
  if (value === null || value === undefined) return '<td class="null">∅</td>';
  const text = String(value).replace(/[<>&]/g, (ch) => ({'<':'&lt;','>':'&gt;','&':'&amp;'}[ch]));
  return `<td title="${text.replace(/"/g, '&quot;')}">${text}</td>`;
}

function renderRows(data) {
  const head = data.columns.map((column) => `<th title="${column.type}">${column.name}</th>`).join('');
  const body = data.rows.map((row) => `<tr>${row.map(cell).join('')}</tr>`).join('');
  $('rows').innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
  $('info').textContent = `всего ${data.total} · показано ${data.offset + 1}–${Math.min(data.offset + data.limit, data.total)}`;
  $('info').className = 'status';
}

async function loadTables() {
  const data = await api('/api/tables');
  $('meta').textContent = `${data.database} · PostgreSQL`;
  const groups = {};
  data.tables.forEach((table) => (groups[table.schema] ||= []).push(table));
  $('tree').innerHTML = Object.entries(groups).map(([schema, list]) => `
    <h3>${schema}</h3>
    ${list.map((table) => `<div class="tbl" data-schema="${table.schema}" data-name="${table.name}">
       <span>${table.name}</span><span>${table.rows}</span></div>`).join('')}
  `).join('');
  document.querySelectorAll('.tbl').forEach((node) => {
    node.onclick = () => openTable(node.dataset.schema, node.dataset.name);
  });
}

async function openTable(schema, table) {
  state.schema = schema; state.table = table; state.offset = 0;
  document.querySelectorAll('.tbl').forEach((node) => {
    node.classList.toggle('active', node.dataset.schema === schema && node.dataset.name === table);
  });
  const data = await api(`/api/table?schema=${schema}&table=${table}&limit=50&offset=0&q=${encodeURIComponent(state.q)}`);
  renderRows(data);
}

async function run(apply) {
  const statement = $('sql').value.trim();
  if (!statement) return;
  $('sqlStatus').textContent = 'выполняем…';
  $('sqlStatus').className = 'status';
  try {
    const data = await api('/api/sql', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sql: statement, apply }),
    });
    if (data.columns.length) {
      renderRows({ columns: data.columns.map((name) => ({ name, type: '' })),
                   rows: data.rows, total: data.rows.length, limit: data.rows.length, offset: 0 });
    }
    $('sqlStatus').textContent = `${data.message} · затронуто строк: ${data.affected}`;
    $('sqlStatus').className = 'status ' + (apply ? 'ok' : 'warn');
    if (apply) loadTables();
  } catch (error) {
    $('sqlStatus').textContent = error.message;
    $('sqlStatus').className = 'status bad';
  }
}

$('search').onclick = () => { state.q = $('q').value.trim(); if (state.table) openTable(state.schema, state.table); };
$('q').onkeydown = (event) => { if (event.key === 'Enter') $('search').click(); };
$('refresh').onclick = () => { loadTables(); if (state.table) openTable(state.schema, state.table); };
$('preview').onclick = () => run(false);
$('apply').onclick = () => { if (confirm('Применить изменения к базе?')) run(true); };
$('delete').onclick = () => {
  if (!confirm('Выполнить DELETE? Сначала лучше нажать «Проверить».')) return;
  run(true);
};

loadTables().catch((error) => { $('meta').textContent = 'ошибка: ' + error.message; });
</script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn

    token_file = Path(settings.MEDIA_DIR).resolve().parent / "db_admin_token.txt"
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(TOKEN, encoding="utf-8")

    url = f"http://127.0.0.1:{PORT}/?token={TOKEN}"
    print("=" * 72, flush=True)
    print("  Панель базы данных карьера", flush=True)
    print(f"  {url}", flush=True)
    print(f"  Токен также сохранён в {token_file}", flush=True)
    print("  DDL запрещён, изменения — в два шага (Проверить → Применить).", flush=True)
    print("=" * 72, flush=True)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
