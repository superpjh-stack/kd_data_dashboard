"""Versioned, read-only workbook ingestion for the v1.5 foundation template.

Operational project/quote tables are deliberately not overwritten by template data.
Formula caches are retained as evidence, never treated as newly calculated values.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import posixpath
import re
import sqlite3
import zipfile
import xml.etree.ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS foundation_imports(
 id INTEGER PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, filename TEXT NOT NULL,
 imported_at TEXT NOT NULL, snapshot TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS foundation_sheets(
 import_id INTEGER NOT NULL REFERENCES foundation_imports(id), name TEXT NOT NULL,
 kind TEXT NOT NULL, headers_json TEXT NOT NULL, row_count INTEGER NOT NULL,
 PRIMARY KEY(import_id,name)
);
CREATE TABLE IF NOT EXISTS foundation_records(
 id INTEGER PRIMARY KEY, import_id INTEGER NOT NULL REFERENCES foundation_imports(id),
 sheet TEXT NOT NULL, source_row INTEGER NOT NULL, record_key TEXT NOT NULL,
 values_json TEXT NOT NULL, cells_json TEXT NOT NULL, design INTEGER NOT NULL,
 issues_json TEXT NOT NULL, UNIQUE(import_id,sheet,source_row)
);
CREATE INDEX IF NOT EXISTS foundation_lookup ON foundation_records(import_id,sheet);
"""


def ensure_schema(db: Path) -> None:
    with sqlite3.connect(db) as con:
        con.executescript(SCHEMA)


def _json(value):
    return json.dumps(value, ensure_ascii=False)


def _blank(value):
    return value is None or str(value).strip() == ""


def read_workbook(path: Path | BytesIO) -> list[dict]:
    with zipfile.ZipFile(path) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ["".join(t.text or "" for t in si.iterfind(".//m:t", NS))
                       for si in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("m:si", NS)]
        styles = ET.fromstring(archive.read("xl/styles.xml"))
        formats = {int(f.get("numFmtId")): f.get("formatCode", "")
                   for f in styles.findall("m:numFmts/m:numFmt", NS)}
        xfs = styles.findall("m:cellXfs/m:xf", NS)
        fills = styles.findall("m:fills/m:fill", NS)
        book = ET.fromstring(archive.read("xl/workbook.xml"))
        prop = book.find("m:workbookPr", NS)
        date1904 = prop is not None and prop.get("date1904") in ("1", "true")
        rels = {r.get("Id"): r.get("Target")
                for r in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
        sheets = []
        for sheet in book.findall("m:sheets/m:sheet", NS):
            target = rels[sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")]
            target = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
            rows = {}
            for row in ET.fromstring(archive.read(target)).findall("m:sheetData/m:row", NS):
                cells = {}
                for cell in row.findall("m:c", NS):
                    ref = cell.get("r")
                    column = re.sub(r"\d", "", ref)
                    node = cell.find("m:v", NS)
                    raw = node.text if node is not None else None
                    kind = cell.get("t", "n")
                    value = raw
                    if kind == "s" and raw is not None:
                        value = strings[int(raw)]
                    elif kind == "inlineStr":
                        value = "".join(t.text or "" for t in cell.iterfind(".//m:t", NS))
                    elif kind == "b" and raw is not None:
                        value = raw == "1"
                    elif kind == "n" and raw is not None:
                        number = float(raw)
                        value = int(number) if number.is_integer() else number
                    xf = xfs[int(cell.get("s", "0"))]
                    fill = fills[int(xf.get("fillId", "0"))].find("m:patternFill/m:fgColor", NS)
                    color = fill.get("rgb", "") if fill is not None else ""
                    fmt = int(xf.get("numFmtId", "0"))
                    date_format = fmt in range(14, 23) or bool(re.search(r"[yd]", formats.get(fmt, ""), re.I))
                    if kind == "n" and raw is not None and date_format:
                        epoch = datetime(1904, 1, 1) if date1904 else datetime(1899, 12, 30)
                        value = (epoch + timedelta(days=float(raw))).date().isoformat()
                    formula = cell.find("m:f", NS)
                    if not _blank(value) or formula is not None:
                        cells[column] = {"cell": ref, "value": value, "raw": raw, "type": kind,
                                         "formula": formula.text or "" if formula is not None else None,
                                         "design": color.upper().endswith("DDEBF7")}
                if cells:
                    rows[int(row.get("r"))] = cells
            sheets.append({"name": sheet.get("name"), "rows": rows})
        return sheets


# Reference columns refer to the workbook's codes, not names guessed from filenames.
REFERENCES = {
    "02": {"F": "08"}, "04": {"D": "08"}, "05": {"H": "03", "L": "04"},
    "07-1": {"B": "06"}, "07-2": {"A": "07-1", "D": "05", "I": "08"},
    "08": {"E": "04", "F": "02"}, "09": {"D": "08", "E": "04"},
    "10": {"A": "02"}, "12": {"B": "08", "L": "03", "M": "09"},
    "13": {"D": "08"}, "14": {"D": "09"}, "15": {"A": "09", "G": "02"},
    "18": {"A": "05", "L": "04", "M": "03", "N": "19"},
    "19": {"B": "03", "D": "06", "L": "08"}, "20": {"E": "06"},
    "21": {"E": "03", "F": "06"}, "22": {"G": "08", "H": "03"},
}
COMPOSITE_KEYS = {"07-1": ("A", "D"), "07-2": ("A", "B", "C", "D"),
                  "10": ("A", "C"), "15": ("A", "C", "E"),
                  "17": ("A", "B", "E", "F"), "18": ("A", "D", "L"),
                  "20": ("A", "B"), "21": ("A", "B")}


def prepare_records(sheets: list[dict]) -> tuple[list[dict], list[dict]]:
    records, metadata = [], []
    for sheet in sheets:
        name, rows = sheet["name"], sheet["rows"]
        prefix = name.split("_")[0]
        reference = prefix in ("0", "00", "23") or name == "코드목록"
        header_row = 3 if name == "코드목록" else 4
        headers = {col: str(c["value"]) for col, c in rows.get(header_row, {}).items() if not _blank(c["value"])}
        if prefix == "0":
            headers = {col: f"{col}열" for col in sorted({c for row in rows.values() for c in row})}
        start = 4 if name == "코드목록" else 1 if prefix == "0" else 5 if prefix in ("00", "01", "23") else 7
        count = 0
        for row_no, cells in rows.items():
            if row_no < start:
                continue
            # Ignore formula-only template tails. A missing key must not hide a populated row.
            literals = {k: c["value"] for k, c in cells.items() if c["formula"] is None and not _blank(c["value"])}
            if not literals or (prefix == "01" and _blank(literals.get("C"))):
                continue
            values = {k: c["value"] for k, c in cells.items()}
            keys = COMPOSITE_KEYS.get(prefix, ("A",))
            key = " / ".join(str(literals.get(k, "")) for k in keys)
            if not key.strip(" / "):
                key = f"미채번 · {row_no}행"
            required = [k for k, label in headers.items() if "★" in label] if not reference else []
            if prefix == "03" and "고객사" in str(values.get("C", "")):
                required += ["F", "I", "J"]
            if prefix == "02" and values.get("E") == "현장 작업자(스마트패드)":
                required += ["F"]
            if prefix == "05" and values.get("D") == "판재":
                required += ["E"]
            if prefix == "21" and values.get("D") == "Y":
                required += ["L"]
            issues = [f"필수 누락: {headers.get(k, k).replace('★', '').strip()} ({k}{row_no})"
                      for k in dict.fromkeys(required) if _blank(values.get(k))]
            hints = rows.get(5, {})
            for col, cell in cells.items():
                if cell["type"] == "e":
                    issues.append(f"엑셀 오류: {cell['cell']} {cell['value']}")
                if "YYYY-MM-DD" in str(hints.get(col, {}).get("value", "")) and not _blank(cell["value"]):
                    try:
                        datetime.strptime(str(cell["value"]), "%Y-%m-%d")
                    except ValueError:
                        issues.append(f"날짜 형식 확인: {cell['cell']}")
            records.append({"sheet": name, "prefix": prefix, "source_row": row_no, "record_key": key,
                            "values": values, "cells": cells, "design": any(c["design"] for c in cells.values()),
                            "issues": issues, "kind": "reference" if reference else "data"})
            count += 1
        metadata.append({"name": name, "kind": "reference" if reference else "data", "headers": headers, "row_count": count})
    codes = {}
    for r in records:
        if r["kind"] == "data" and not _blank(r["values"].get("A")):
            codes.setdefault(r["prefix"], set()).add(str(r["values"]["A"]))
    counts = Counter((r["sheet"], r["record_key"]) for r in records if r["kind"] == "data")
    for r in records:
        if r["kind"] != "data":
            continue
        if counts[(r["sheet"], r["record_key"])] > 1:
            r["issues"].append("중복 업무 키: 같은 코드·버전·일자 조합 확인 필요")
        for col, target in REFERENCES.get(r["prefix"], {}).items():
            value = r["values"].get(col)
            if not _blank(value):
                for code in re.split(r"[,，\n]", str(value)):
                    if code.strip() not in codes.get(target, set()):
                        r["issues"].append(f"참조 미확인: {col}{r['source_row']} → {target} 시트의 {code.strip()}")
    return records, metadata


def import_workbook(path: Path, db: Path) -> dict:
    path = path.resolve()
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    records, sheets = prepare_records(read_workbook(BytesIO(content)))
    if not {"03_거래처", "21_견적이력", "22_RAG문서"}.issubset({s["name"] for s in sheets}):
        raise ValueError("경동 기초데이터 입력양식의 필수 시트가 없습니다.")
    # Snapshot immutable bytes so provenance remains valid if the original is edited later.
    folder = db.parent / "foundation-sources"
    folder.mkdir(parents=True, exist_ok=True)
    snapshot = folder / f"{digest}.xlsx"
    if not snapshot.exists():
        snapshot.write_bytes(content)
    ensure_schema(db)
    with sqlite3.connect(db) as con:
        con.execute("BEGIN IMMEDIATE")
        previous = con.execute("SELECT id FROM foundation_imports WHERE sha256=?", (digest,)).fetchone()
        con.execute("UPDATE foundation_imports SET active=0")
        if previous:
            con.execute("UPDATE foundation_imports SET active=1 WHERE id=?", (previous[0],))
        else:
            import_id = con.execute(
                "INSERT INTO foundation_imports(sha256,filename,imported_at,snapshot,active) VALUES(?,?,?,?,1)",
                (digest, path.name, datetime.now(timezone.utc).isoformat(), snapshot.name)).lastrowid
            con.executemany("INSERT INTO foundation_sheets VALUES(?,?,?,?,?)",
                            [(import_id, s["name"], s["kind"], _json(s["headers"]), s["row_count"]) for s in sheets])
            con.executemany("""INSERT INTO foundation_records(import_id,sheet,source_row,record_key,
                            values_json,cells_json,design,issues_json) VALUES(?,?,?,?,?,?,?,?)""",
                            [(import_id, r["sheet"], r["source_row"], r["record_key"], _json(r["values"]),
                              _json(r["cells"]), int(r["design"]), _json(r["issues"])) for r in records])
    result = summary(db)
    result["reused"] = bool(previous)
    return result


def _connect(db):
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


def _normalize(value):
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _records(con):
    rows = con.execute("""SELECT r.*,s.kind FROM foundation_records r
        JOIN foundation_imports i ON i.id=r.import_id AND i.active=1
        JOIN foundation_sheets s ON s.import_id=r.import_id AND s.name=r.sheet
        ORDER BY r.sheet,r.source_row""").fetchall()
    existing = {}
    if con.execute("SELECT 1 FROM sqlite_master WHERE name='quotes'").fetchone():
        for q in con.execute("SELECT id,project_id,quote_no FROM quotes WHERE quote_no IS NOT NULL"):
            key = _normalize(q["quote_no"])
            if key:
                existing.setdefault(key, []).append({"id": q["id"], "project_id": q["project_id"]})
    result = []
    for row in rows:
        item = dict(row)
        item["values"] = json.loads(item.pop("values_json"))
        item["cells"] = json.loads(item.pop("cells_json"))
        item["issues"] = json.loads(item.pop("issues_json"))
        item["overlap"] = existing.get(_normalize(item["values"].get("A")), []) if item["sheet"] == "21_견적이력" else []
        item["status"] = "검토 필요" if item["issues"] else "설계안 확인 필요" if item["design"] else "입력값 적재"
        result.append(item)
    return result


def summary(db: Path) -> dict:
    with _connect(db) as con:
        source = con.execute("SELECT id,sha256,filename,imported_at FROM foundation_imports WHERE active=1").fetchone()
        sheets = [dict(r) for r in con.execute("""SELECT s.* FROM foundation_sheets s JOIN foundation_imports i
                    ON s.import_id=i.id WHERE i.active=1 ORDER BY s.name""")]
        rows = _records(con)
        for s in sheets:
            s["headers"] = json.loads(s.pop("headers_json"))
            subset = [r for r in rows if r["sheet"] == s["name"]]
            s["issue_rows"] = sum(bool(r["issues"]) for r in subset)
            s["design_rows"] = sum(r["design"] for r in subset)
        data = [r for r in rows if r["kind"] == "data"]
        quotes = [r for r in data if r["sheet"] == "21_견적이력"]
        dates = sorted(str(r["values"]["B"]) for r in quotes
                       if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(r["values"].get("B", ""))))
        amounts = [r["values"]["K"] for r in quotes if isinstance(r["values"].get("K"), (int, float))]
        analytics = {
            "quote_rows": len(quotes), "quote_amount_rows": len(amounts),
            "quote_source_total": sum(amounts), "quote_date_from": dates[0] if dates else None,
            "quote_date_to": dates[-1] if dates else None,
            "actual_cost_rows": sum(isinstance(r["values"].get("L"), (int, float)) for r in quotes),
            "customer_types": dict(Counter(str(r["values"].get("C") or "미입력") for r in data if r["sheet"] == "03_거래처")),
            "model_families": dict(Counter(str(r["values"].get("C") or "미입력") for r in data if r["sheet"] == "06_제품모델")),
            "missing_fields": dict(Counter(issue.split(" (")[0].removeprefix("필수 누락: ")
                                           for r in data for issue in r["issues"] if issue.startswith("필수 누락:")).most_common(8)),
            "empty_sheets": [s["name"] for s in sheets if s["kind"] == "data" and not s["row_count"]],
        }
        return {"source": dict(source) if source else None, "sheets": sheets, "records": len(data),
                "analytics": analytics,
                "reference_records": len(rows) - len(data), "issue_rows": sum(bool(r["issues"]) for r in data),
                "design_rows": sum(r["design"] for r in data), "quote_overlap_rows": sum(bool(r["overlap"]) for r in data),
                "rules": ["일반 입력 시트의 6행 예시와 수식만 있는 빈 행 제외", "하늘색 셀 포함 행은 설계안 확인 필요",
                          "필수값·참조 코드·날짜·중복 업무 키 검사", "수식은 원문과 저장된 계산값 보존, 재계산하지 않음",
                          "새 견적은 별도 자료이며 기존 반응기 견적·수주 KPI에 합산하지 않음",
                          "입력값 적재는 업무 승인이나 사용자 계정 생성을 의미하지 않음"]}


def records(db: Path, sheet: str = "", q: str = "", issues_only: bool = False,
            offset: int = 0, limit: int = 100) -> dict:
    with _connect(db) as con:
        rows = _records(con)
    rows = [r for r in rows if (not sheet or r["sheet"] == sheet)
            and (not issues_only or r["issues"])
            and (not q or q.casefold() in _json([r["values"], r["issues"], r["record_key"], r["sheet"]]).casefold())]
    return {"total": len(rows), "items": rows[offset:offset + limit]}


def snapshot_path(db: Path) -> Path | None:
    with _connect(db) as con:
        row = con.execute("SELECT snapshot FROM foundation_imports WHERE active=1").fetchone()
    if not row:
        return None
    folder = (db.parent / "foundation-sources").resolve()
    path = (folder / row[0]).resolve()
    return path if path.parent == folder and path.is_file() else None
