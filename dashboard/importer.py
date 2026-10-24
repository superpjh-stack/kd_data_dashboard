from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

from .scanner import scan_files


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects(
  id TEXT PRIMARY KEY, name TEXT NOT NULL, customer TEXT, item TEXT, code TEXT, status TEXT,
  order_date TEXT, order_amount INTEGER, order_kind TEXT, order_desc TEXT, notes_json TEXT NOT NULL,
  counts_json TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quotes(
  id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, quote_date TEXT, quote_no TEXT,
  recipient TEXT, item TEXT, total_amount INTEGER, negotiated_amount INTEGER, vat TEXT, issuer TEXT,
  reactor_related INTEGER NOT NULL, relevant INTEGER NOT NULL, filename TEXT, unit TEXT, repo_path TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS files(
  id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, project_folder TEXT, category TEXT,
  subtype TEXT, filename TEXT, extension TEXT, size INTEGER, modified_at TEXT, repo_path TEXT,
  source_path TEXT, md5 TEXT, body_text TEXT
);
CREATE INDEX IF NOT EXISTS idx_quotes_project ON quotes(project_id);
CREATE INDEX IF NOT EXISTS idx_files_project ON files(project_id);
CREATE INDEX IF NOT EXISTS idx_files_name ON files(filename);
"""


def _integer(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except ValueError:
        return None


def rebuild_database(root: Path, db: Path, portfolio_root: Path | None = None) -> dict[str, int]:
    cases = json.loads((root / "bom/data/cases_pipeline.json").read_text(encoding="utf-8-sig"))
    connection = sqlite3.connect(db)
    try:
        connection.executescript(SCHEMA)
        connection.execute("BEGIN")
        connection.execute("DELETE FROM projects")
        connection.execute("DELETE FROM quotes")
        connection.execute("DELETE FROM files")
        for case in cases:
            order = case.get("order") or {}
            connection.execute(
                "INSERT INTO projects VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (case["id"], case.get("name", ""), case.get("customer", ""), case.get("item", ""),
                 case.get("code", ""), case.get("status", ""), order.get("date"), _integer(order.get("amount")),
                 order.get("kind"), order.get("desc"), json.dumps(case.get("notes", []), ensure_ascii=False),
                 json.dumps(case.get("counts", {}), ensure_ascii=False), json.dumps(case, ensure_ascii=False)),
            )
        with (root / "index/quotes.csv").open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                connection.execute(
                    """INSERT INTO quotes(project_id,quote_date,quote_no,recipient,item,total_amount,negotiated_amount,
                    vat,issuer,reactor_related,relevant,filename,unit,repo_path,note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (row["건ID"], row["견적일"], row["견적번호"], row["수신처"], row["품명"],
                     _integer(row["합계금액(원)"]), _integer(row["네고금액(원)"]), row["VAT"], row["발행구분"],
                     int(row["반응기관련"].strip() == "O"), int(row["해당건견적"].strip() == "O"),
                     row["파일명"], row["단위(시트/PDF)"], row["리포지토리경로"], row["비고"]),
                )
        with (root / "index/files.csv").open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                connection.execute(
                    """INSERT INTO files(project_id,project_folder,category,subtype,filename,extension,size,
                    modified_at,repo_path,source_path,md5,body_text) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (row["건ID"], row["건폴더"], row["대분류"], row["세부구분"], row["파일명"], row["확장자"],
                     _integer(row["크기(byte)"]) or 0, row["수정일"], row["리포지토리경로"], row["원본경로"],
                     row["md5"], row["본문텍스트"]),
                )
        connection.execute("INSERT OR REPLACE INTO meta VALUES('data_root', ?)", (str(root),))
        connection.execute("INSERT OR REPLACE INTO meta VALUES('project_count', ?)", (str(len(cases)),))
        connection.commit()
        result = {
            "projects": len(cases),
            "quotes": connection.execute("SELECT COUNT(*) FROM quotes").fetchone()[0],
            "files": connection.execute("SELECT COUNT(*) FROM files").fetchone()[0],
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    if portfolio_root is not None:
        result["manufacturing_files"] = scan_files(portfolio_root, db)["scanned"]
    return result
