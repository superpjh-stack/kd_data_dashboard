from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .classifier import customer_candidate, equipment_type, file_class, normalized, project_codes, project_label, source_year


SCAN_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ingestion_runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT,
  status TEXT NOT NULL, scanned INTEGER NOT NULL DEFAULT 0, changed INTEGER NOT NULL DEFAULT 0,
  missing INTEGER NOT NULL DEFAULT 0, errors INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS manufacturing_files(
  id INTEGER PRIMARY KEY AUTOINCREMENT, relative_path TEXT NOT NULL UNIQUE, filename TEXT NOT NULL,
  extension TEXT NOT NULL, size INTEGER NOT NULL, modified_ns INTEGER NOT NULL, source_year INTEGER,
  project_code TEXT, equipment_type TEXT NOT NULL, classification TEXT NOT NULL,
  open_allowed INTEGER NOT NULL, sha256 TEXT, exists_flag INTEGER NOT NULL DEFAULT 1,
  classification_confidence REAL NOT NULL DEFAULT 0, last_run_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_mf_year ON manufacturing_files(source_year);
CREATE INDEX IF NOT EXISTS idx_mf_project ON manufacturing_files(project_code);
CREATE INDEX IF NOT EXISTS idx_mf_equipment ON manufacturing_files(equipment_type);
CREATE INDEX IF NOT EXISTS idx_mf_class ON manufacturing_files(classification);
CREATE TABLE IF NOT EXISTS manufacturing_projects(
  project_code TEXT PRIMARY KEY, source_year INTEGER, label TEXT NOT NULL, customer_candidate TEXT NOT NULL,
  customer_confidence REAL NOT NULL, equipment_type TEXT NOT NULL, file_count INTEGER NOT NULL DEFAULT 0,
  total_bytes INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS scan_errors(
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL, relative_path TEXT,
  error_type TEXT NOT NULL, message TEXT NOT NULL
);
"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scan_files(root: Path, db: Path, compute_hashes: bool = False) -> dict[str, int]:
    root = root.resolve()
    con = sqlite3.connect(db)
    now = datetime.now(timezone.utc).isoformat()
    try:
        con.executescript(SCAN_SCHEMA)
        previous_root = con.execute("SELECT value FROM meta WHERE key='portfolio_root'").fetchone()
        if previous_root is None or previous_root[0] != str(root):
            con.execute("DELETE FROM manufacturing_files")
            con.execute("DELETE FROM manufacturing_projects")
            con.execute("DELETE FROM scan_errors")
        con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('portfolio_root',?)", (str(root),))
        run_id = con.execute("INSERT INTO ingestion_runs(started_at,status) VALUES(?,?)", (now, "running")).lastrowid
        con.execute("UPDATE manufacturing_files SET exists_flag=0")
        scanned = changed = errors = 0
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            scanned += 1
            relative = path.relative_to(root)
            relative_text = normalized(relative.as_posix())
            try:
                stat = path.stat()
                old = con.execute("SELECT size,modified_ns,sha256 FROM manufacturing_files WHERE relative_path=?", (relative_text,)).fetchone()
                is_changed = old is None or old[0] != stat.st_size or old[1] != stat.st_mtime_ns
                classification, open_allowed = file_class(path)
                codes = project_codes(relative_text)
                equipment, confidence = equipment_type(relative_text)
                digest = _sha256(path) if compute_hashes and is_changed else (old[2] if old else None)
                con.execute(
                    """INSERT INTO manufacturing_files(relative_path,filename,extension,size,modified_ns,source_year,
                    project_code,equipment_type,classification,open_allowed,sha256,exists_flag,classification_confidence,last_run_id)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(relative_path) DO UPDATE SET
                    filename=excluded.filename,extension=excluded.extension,size=excluded.size,modified_ns=excluded.modified_ns,
                    source_year=excluded.source_year,project_code=excluded.project_code,equipment_type=excluded.equipment_type,
                    classification=excluded.classification,open_allowed=excluded.open_allowed,
                    sha256=COALESCE(excluded.sha256,manufacturing_files.sha256),exists_flag=1,
                    classification_confidence=excluded.classification_confidence,last_run_id=excluded.last_run_id""",
                    (relative_text, normalized(path.name), path.suffix.casefold(), stat.st_size, stat.st_mtime_ns,
                     source_year(relative), codes[0] if codes else None, equipment, classification, int(open_allowed),
                     digest, 1, confidence, run_id),
                )
                changed += int(is_changed)
            except Exception as exc:
                errors += 1
                con.execute("INSERT INTO scan_errors(run_id,relative_path,error_type,message) VALUES(?,?,?,?)",
                            (run_id, relative_text, type(exc).__name__, str(exc)))
        con.execute("DELETE FROM manufacturing_projects")
        project_rows = con.execute(
            """SELECT project_code,MIN(source_year),COUNT(*),SUM(size),
            GROUP_CONCAT(relative_path,'\n') FROM manufacturing_files
            WHERE exists_flag=1 AND project_code IS NOT NULL GROUP BY project_code"""
        ).fetchall()
        for code, year, file_count, total_bytes, paths in project_rows:
            candidates = [Path(value) for value in paths.split("\n")]
            labels = [project_label(path, code) for path in candidates]
            label = next((value for value in labels if value), "미분류")
            customer, customer_confidence = customer_candidate(label)
            equipment, _ = equipment_type(" ".join(str(path) for path in candidates[:30]))
            con.execute("INSERT INTO manufacturing_projects VALUES(?,?,?,?,?,?,?,?)",
                        (code, year, label, customer, customer_confidence, equipment, file_count, total_bytes))
        missing = con.execute("SELECT COUNT(*) FROM manufacturing_files WHERE exists_flag=0").fetchone()[0]
        con.execute("UPDATE ingestion_runs SET finished_at=?,status=?,scanned=?,changed=?,missing=?,errors=? WHERE id=?",
                    (datetime.now(timezone.utc).isoformat(), "complete_with_errors" if errors else "complete",
                     scanned, changed, missing, errors, run_id))
        con.commit()
        return {"run_id": run_id, "scanned": scanned, "changed": changed, "missing": missing, "errors": errors}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
