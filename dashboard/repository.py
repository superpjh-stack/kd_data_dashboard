from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class Repository:
    def __init__(self, db: Path, root: Path, portfolio_root: Path | None = None):
        self.db = db
        self.root = root.resolve()
        self.portfolio_root = (portfolio_root or root).resolve()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
        return [dict(row) for row in cursor.fetchall()]

    def summary(self) -> dict[str, Any]:
        with self.connect() as con:
            projects = self.rows(con.execute("SELECT * FROM projects ORDER BY id"))
            valid_quotes = self.rows(con.execute(
                "SELECT * FROM quotes WHERE relevant=1 AND issuer LIKE '%경동 발행%' AND project_id <> 'R12' AND total_amount IS NOT NULL"
            ))
        order_total = sum(row["order_amount"] or 0 for row in projects)
        ordered = [row for row in projects if "수주" in row["status"]]
        quoted_ids = {row["project_id"] for row in valid_quotes}
        customer_count = len({row["customer"] for row in projects if row["customer"]})
        year_totals: dict[str, dict[str, int]] = {}
        for row in valid_quotes:
            year = (row["quote_date"] or "미상")[:4]
            year_totals.setdefault(year, {"quotes": 0, "orders": 0})["quotes"] += row["total_amount"] or 0
        for row in projects:
            if row["order_date"]:
                year_totals.setdefault(row["order_date"][:4], {"quotes": 0, "orders": 0})["orders"] += row["order_amount"] or 0
        return {
            "kpis": {
                "order_amount": order_total,
                "quote_amount": sum(row["total_amount"] or 0 for row in valid_quotes),
                "ordered_projects": len(ordered),
                "customers": customer_count,
                "conversion_rate": round(len({p["id"] for p in ordered} & quoted_ids) / len(quoted_ids) * 100, 1) if quoted_ids else None,
            },
            "timeline": [{"year": y, **v} for y, v in sorted(year_totals.items())],
            "projects": [self._project_summary(row) for row in projects],
            "rules": ["해당건견적=O", "경동 발행", "R12 전체 플랜트 견적 제외", "계약·발주 확인 금액만 수주액 포함"],
        }

    def projects(self, q: str = "", status: str = "") -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = self.rows(con.execute("SELECT * FROM projects ORDER BY id"))
        items = [self._project_summary(row) for row in rows]
        if q:
            needle = q.casefold()
            items = [item for item in items if needle in " ".join(str(v) for v in item.values()).casefold()]
        if status:
            items = [item for item in items if status in item["status"]]
        return items

    def project(self, project_id: str) -> dict[str, Any] | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if not row:
                return None
            payload = json.loads(row["payload_json"])
            payload["files"] = self.rows(con.execute("SELECT * FROM files WHERE project_id=? ORDER BY category, modified_at DESC", (project_id,)))
            payload["quote_rows"] = self.rows(con.execute("SELECT * FROM quotes WHERE project_id=? ORDER BY quote_date DESC, id DESC", (project_id,)))
            payload["quality_issues"] = self._quality_for(dict(row), payload)
            return payload

    def quotes(self, q: str = "", issuer: str = "", relevant_only: bool = False) -> list[dict[str, Any]]:
        clauses, params = ["1=1"], []
        if relevant_only:
            clauses.append("relevant=1")
        if issuer:
            clauses.append("issuer LIKE ?")
            params.append(f"%{issuer}%")
        if q:
            clauses.append("(recipient LIKE ? OR item LIKE ? OR quote_no LIKE ? OR project_id LIKE ?)")
            params.extend([f"%{q}%"] * 4)
        with self.connect() as con:
            return self.rows(con.execute(f"SELECT * FROM quotes WHERE {' AND '.join(clauses)} ORDER BY quote_date DESC, id DESC LIMIT 1000", params))

    def files(self, q: str = "", category: str = "", extension: str = "", project_id: str = "") -> list[dict[str, Any]]:
        clauses, params = ["1=1"], []
        for field, value in (("category", category), ("extension", extension), ("project_id", project_id)):
            if value:
                clauses.append(f"{field}=?")
                params.append(value)
        if q:
            clauses.append("(filename LIKE ? OR subtype LIKE ? OR repo_path LIKE ?)")
            params.extend([f"%{q}%"] * 3)
        with self.connect() as con:
            rows = self.rows(con.execute(f"SELECT * FROM files WHERE {' AND '.join(clauses)} ORDER BY modified_at DESC, id DESC LIMIT 1000", params))
        for row in rows:
            row["exists"] = (self.root / row["repo_path"]).is_file()
        return rows

    def quality(self) -> list[dict[str, Any]]:
        issues = []
        with self.connect() as con:
            for row in self.rows(con.execute("SELECT * FROM projects ORDER BY id")):
                payload = json.loads(row["payload_json"])
                issues.extend(self._quality_for(row, payload))
        return issues

    def portfolio_quality(self) -> list[dict[str, Any]]:
        with self.connect() as con:
            unclassified = con.execute(
                "SELECT COUNT(*) FROM manufacturing_files WHERE exists_flag=1 AND project_code IS NULL"
            ).fetchone()[0]
            blocked = con.execute(
                "SELECT COUNT(*) FROM manufacturing_files WHERE exists_flag=1 AND open_allowed=0"
            ).fetchone()[0]
            missing = con.execute("SELECT COUNT(*) FROM manufacturing_files WHERE exists_flag=0").fetchone()[0]
            scan_errors = con.execute("SELECT COUNT(*) FROM scan_errors").fetchone()[0]
        issues = []
        if unclassified:
            issues.append({"project_id": "전체", "severity": "info", "type": "프로젝트 미분류",
                           "message": f"{unclassified:,}개 파일은 프로젝트 코드가 확인되지 않았습니다."})
        if blocked:
            issues.append({"project_id": "전체", "severity": "info", "type": "안전 격리",
                           "message": f"{blocked:,}개 실행·임시·백업 파일의 원본 열기를 차단했습니다."})
        if missing:
            issues.append({"project_id": "전체", "severity": "warning", "type": "원본 경로 끊김",
                           "message": f"이전 색인 중 {missing:,}개 파일이 현재 원본에 없습니다."})
        if scan_errors:
            issues.append({"project_id": "전체", "severity": "warning", "type": "스캔 오류",
                           "message": f"누적 {scan_errors:,}개 파일 처리 오류가 기록되었습니다."})
        return issues

    def resolve_file(self, file_id: int) -> Path | None:
        with self.connect() as con:
            row = con.execute("SELECT repo_path FROM files WHERE id=?", (file_id,)).fetchone()
        if not row:
            return None
        candidate = (self.root / row["repo_path"]).resolve()
        if self.root not in candidate.parents or not candidate.is_file():
            return None
        return candidate

    def portfolio_summary(self) -> dict[str, Any]:
        with self.connect() as con:
            total = con.execute(
                "SELECT COUNT(*),COALESCE(SUM(size),0),COUNT(DISTINCT project_code) FROM manufacturing_files WHERE exists_flag=1"
            ).fetchone()
            by_year = self.rows(con.execute(
                """SELECT COALESCE(CAST(source_year AS TEXT),'미상') year,COUNT(*) files,COALESCE(SUM(size),0) bytes,
                COUNT(DISTINCT project_code) projects FROM manufacturing_files WHERE exists_flag=1 GROUP BY source_year ORDER BY source_year"""
            ))
            by_type = self.rows(con.execute(
                "SELECT classification type,COUNT(*) files,COALESCE(SUM(size),0) bytes FROM manufacturing_files WHERE exists_flag=1 GROUP BY classification ORDER BY files DESC"
            ))
            equipment = self.rows(con.execute(
                "SELECT equipment_type equipment,COUNT(*) files,COUNT(DISTINCT project_code) projects FROM manufacturing_files WHERE exists_flag=1 GROUP BY equipment_type ORDER BY files DESC"
            ))
            customers = self.rows(con.execute(
                """SELECT customer_candidate customer,COUNT(*) projects,SUM(file_count) files,SUM(total_bytes) bytes
                FROM manufacturing_projects GROUP BY customer_candidate ORDER BY projects DESC,files DESC LIMIT 30"""
            ))
        return {"files": total[0], "bytes": total[1], "projects": total[2], "by_year": by_year,
                "by_type": by_type, "equipment": equipment, "customers": customers,
                "customers_count": sum(1 for row in customers if row["customer"] != "미분류")}

    def portfolio_customers(self) -> list[dict[str, Any]]:
        with self.connect() as con:
            return self.rows(con.execute(
                """SELECT customer_candidate customer,COUNT(*) projects,SUM(file_count) files,SUM(total_bytes) bytes,
                ROUND(AVG(customer_confidence),2) confidence FROM manufacturing_projects
                GROUP BY customer_candidate ORDER BY projects DESC,files DESC"""
            ))

    def portfolio_activity(self) -> list[dict[str, Any]]:
        with self.connect() as con:
            return self.rows(con.execute(
                """SELECT substr(datetime(modified_ns / 1000000000,'unixepoch'),1,7) month,
                COUNT(*) files,COALESCE(SUM(size),0) bytes FROM manufacturing_files
                WHERE exists_flag=1 GROUP BY month ORDER BY month"""
            ))

    def manufacturing_files(self, q: str = "", year: str = "", classification: str = "",
                            equipment: str = "", project_code: str = "", limit: int = 100,
                            offset: int = 0) -> dict[str, Any]:
        clauses, params = ["exists_flag=1"], []
        for field, value in (("source_year", year), ("classification", classification),
                             ("equipment_type", equipment), ("project_code", project_code)):
            if value:
                clauses.append(f"{field}=?")
                params.append(value)
        if q:
            clauses.append("(filename LIKE ? OR relative_path LIKE ? OR project_code LIKE ?)")
            params.extend([f"%{q}%"] * 3)
        where = " AND ".join(clauses)
        with self.connect() as con:
            total = con.execute(f"SELECT COUNT(*) FROM manufacturing_files WHERE {where}", params).fetchone()[0]
            rows = self.rows(con.execute(
                f"""SELECT id,relative_path,filename,extension,size,source_year,project_code,equipment_type,
                classification,open_allowed FROM manufacturing_files WHERE {where}
                ORDER BY modified_ns DESC,id DESC LIMIT ? OFFSET ?""", [*params, limit, offset]
            ))
        return {"items": rows, "total": total, "limit": limit, "offset": offset}

    def resolve_manufacturing_file(self, file_id: int) -> Path | None:
        with self.connect() as con:
            row = con.execute(
                "SELECT relative_path,open_allowed FROM manufacturing_files WHERE id=? AND exists_flag=1", (file_id,)
            ).fetchone()
        if not row or not row["open_allowed"]:
            return None
        candidate = (self.portfolio_root / row["relative_path"]).resolve()
        if self.portfolio_root not in candidate.parents or not candidate.is_file():
            return None
        return candidate

    def drawings(self) -> list[dict[str, Any]]:
        with self.connect() as con:
            return self.rows(con.execute(
                """SELECT id,project_code,filename,relative_path,extension,source_year,equipment_type,size
                FROM manufacturing_files WHERE exists_flag=1 AND classification='도면·CAD'
                ORDER BY source_year DESC,project_code,filename LIMIT 2000"""
            ))

    @staticmethod
    def _project_summary(row: dict[str, Any]) -> dict[str, Any]:
        return {key: row[key] for key in ("id", "name", "customer", "item", "code", "status", "order_date", "order_amount")} | {
            "counts": json.loads(row["counts_json"]), "notes": json.loads(row["notes_json"])
        }

    @staticmethod
    def _quality_for(row: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
        issues = []
        if "수주" in row["status"] and row.get("order_amount") is None:
            issues.append({"project_id": row["id"], "severity": "warning", "type": "수주액 미확인", "message": "계약·고객 발주 금액 근거가 없습니다."})
        if payload.get("drawings") and not payload.get("latest"):
            issues.append({"project_id": row["id"], "severity": "warning", "type": "최신 도면 미확정", "message": "도면은 있으나 최신본 표시가 없습니다."})
        failed = sum(1 for drawing in payload.get("drawings", []) if drawing.get("status") == "read_fail")
        if failed:
            issues.append({"project_id": row["id"], "severity": "info", "type": "도면 해독 실패", "message": f"{failed}개 DWG/CAD의 표 정보를 읽지 못했습니다."})
        for note in payload.get("notes", []):
            if "없" in note or "못" in note or "필요" in note:
                issues.append({"project_id": row["id"], "severity": "info", "type": "확인 필요", "message": note})
        return issues
