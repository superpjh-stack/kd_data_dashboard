from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .repository import Repository


def eda(repo: Repository) -> dict[str, Any]:
    summary = repo.summary()
    projects = summary["projects"]
    reactor_projects = [p for p in projects if p["id"].startswith("R")]
    ordered = [p for p in reactor_projects if "수주" in p["status"]]
    known_orders = [p for p in ordered if p.get("order_amount") is not None]
    with repo.connect() as con:
        quotes = repo.rows(con.execute(
            """SELECT project_id,quote_date,total_amount,issuer,relevant FROM quotes
            WHERE relevant=1 AND project_id<>'R12' ORDER BY quote_date"""
        ))
        drawing_counts = repo.rows(con.execute(
            """SELECT project_code,COUNT(*) drawings FROM manufacturing_files
            WHERE exists_flag=1 AND classification='도면·CAD' AND project_code IS NOT NULL
            GROUP BY project_code ORDER BY drawings DESC LIMIT 30"""
        ))
    amounts = sorted(p["order_amount"] for p in known_orders)
    return {
        "scope": "반응기·견적·수주·도면",
        "samples": {"projects": len(reactor_projects), "ordered": len(ordered),
                    "known_order_amount": len(known_orders), "quotes": len(quotes)},
        "excluded": {"unknown_order_amount": len(ordered) - len(known_orders), "reference_project": 1},
        "order_amount": {"min": amounts[0] if amounts else None, "max": amounts[-1] if amounts else None,
                         "median": amounts[len(amounts) // 2] if amounts else None},
        "timeline": summary["timeline"],
        "drawing_activity": drawing_counts,
        "rules": summary["rules"],
    }


def ml_readiness(repo: Repository) -> dict[str, Any]:
    report = eda(repo)
    samples = report["samples"]
    regression_ready = samples["known_order_amount"] >= 30
    classification_ready = samples["quotes"] >= 50 and samples["ordered"] >= 15
    ready = regression_ready or classification_ready
    recommendations = []
    if not regression_ready:
        recommendations.append("근거가 확인된 수주금액 표본을 최소 30건까지 확보하세요.")
    if not classification_ready:
        recommendations.append("견적-수주 연결 표본을 유지하고 수주 사례를 최소 15건까지 확보하세요.")
    recommendations.append("설비 용량, 재질, 납기, 견적 당시 도면 수를 일관된 필드로 수집하세요.")
    return {"ready": ready, "model_published": False, "tasks": {
        "quote_range": {"ready": regression_ready, "samples": samples["known_order_amount"]},
        "conversion": {"ready": classification_ready, "samples": samples["quotes"]},
        "similar_projects": {"ready": samples["projects"] >= 5, "samples": samples["projects"]},
    }, "recommendations": recommendations, "leakage_excluded": ["수주 후 도면 수", "납품 후 문서 수", "최종 상태"]}


def _csv_rows(root: Path, name: str) -> list[dict[str, str]]:
    path = root / "bom" / "data" / name
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _first_number(value: str | None) -> int | float | None:
    if value is None or not str(value).strip():
        return None
    try:
        number = float(str(value).replace(",", "").strip())
        return int(number) if number.is_integer() else number
    except ValueError:
        return None


def golden_dataset(repo: Repository) -> dict[str, Any]:
    """Build an auditable seed dataset from existing structured extracts."""
    status_rows = _csv_rows(repo.root, "drawings_status.csv")
    design_rows = _csv_rows(repo.root, "drawing_design_data.csv")
    part_rows = _csv_rows(repo.root, "drawing_parts.csv")
    nozzle_rows = _csv_rows(repo.root, "drawing_nozzles.csv")
    cad_samples: list[dict[str, Any]] = []
    for row in part_rows[:3]:
        cad_samples.append({
            "sample_id": f"CAD-PART-{len(cad_samples) + 1:03d}", "task": "CAD 객체인식",
            "project_id": row.get("case"), "source_file": row.get("file"), "drawing_no": row.get("dwg_no"),
            "object_type": "부품", "object_label": row.get("desc"), "material": row.get("mat"),
            "spec": row.get("spec"), "quantity": _first_number(row.get("qty")),
            "annotation_status": "structured_extract_needs_review",
            "evidence": f"부품 No.{row.get('no')}, latest={row.get('latest') or '-'}",
        })
    for row in nozzle_rows[:3]:
        cad_samples.append({
            "sample_id": f"CAD-NOZZLE-{len(cad_samples) + 1:03d}", "task": "CAD 객체인식",
            "project_id": row.get("case"), "source_file": row.get("file"), "drawing_no": row.get("dwg_no"),
            "object_type": "노즐", "object_label": row.get("service") or row.get("type") or "노즐",
            "material": row.get("mat"),
            "spec": " / ".join(value for value in [row.get("size"), row.get("type"), row.get("rating"), row.get("sch")] if value),
            "quantity": _first_number(row.get("qty")),
            "annotation_status": "structured_extract_needs_review",
            "evidence": f"노즐 No.{row.get('no')}, latest={row.get('latest') or '-'}",
        })
    for row in design_rows[:2]:
        parts = [value.strip() for value in row.get("row", "").split("|") if value.strip()]
        cad_samples.append({
            "sample_id": f"CAD-ATTR-{len(cad_samples) + 1:03d}", "task": "CAD 객체인식",
            "project_id": row.get("case"), "source_file": row.get("file"), "drawing_no": row.get("dwg_no"),
            "object_type": "설계속성", "object_label": parts[0] if parts else "미분류", "material": None,
            "spec": " | ".join(parts[1:]) if len(parts) > 1 else None, "quantity": None,
            "annotation_status": "structured_extract_needs_review", "evidence": f"drawing_design_data row={row.get('row')}",
        })
    with repo.connect() as con:
        quote_rows = repo.rows(con.execute(
            """SELECT project_id,quote_no,quote_date,recipient,item,total_amount,filename,repo_path
            FROM quotes WHERE relevant=1 AND issuer LIKE '%경동 발행%' AND total_amount IS NOT NULL
            ORDER BY quote_date DESC, id DESC LIMIT 5"""
        ))
        cad_total = con.execute("SELECT COUNT(*) FROM manufacturing_files WHERE classification='도면·CAD'").fetchone()[0]
        cad_linked = con.execute("SELECT COUNT(*) FROM manufacturing_files WHERE classification='도면·CAD' AND project_code IS NOT NULL").fetchone()[0]
        priced_relevant = con.execute("SELECT COUNT(*) FROM quotes WHERE relevant=1 AND total_amount IS NOT NULL").fetchone()[0]
        issued_priced = con.execute("SELECT COUNT(*) FROM quotes WHERE relevant=1 AND issuer LIKE '%경동 발행%' AND total_amount IS NOT NULL").fetchone()[0]
    quote_samples = [{
        "sample_id": f"QUOTE-{index:03d}", "task": "견적자동화", "project_id": row.get("project_id"),
        "quote_no": row.get("quote_no"), "quote_date": row.get("quote_date"), "customer": row.get("recipient"),
        "item": row.get("item"), "material": None, "capacity": None, "quantity": None,
        "amount": row.get("total_amount"), "source_file": row.get("filename"),
        "annotation_status": "amount_verified_fields_missing", "evidence": row.get("repo_path"),
    } for index, row in enumerate(quote_rows, 1)]
    status_ok = sum(row.get("status") == "ok" for row in status_rows)
    status_failed = sum(row.get("status") == "read_fail" for row in status_rows)
    table_rows = sum(bool(row.get("tables")) for row in status_rows)
    return {
        "title": "CAD 객체인식·견적자동화 골든데이터셋 시드",
        "purpose": "검수 가능한 원본 근거를 기준으로 객체 라벨과 견적 입력 필드를 정규화하기 위한 샘플",
        "status": "seed_only",
        "schema": {
            "cad_object": ["sample_id", "project_id", "source_file", "drawing_no", "object_type", "object_label", "material", "spec", "quantity", "annotation_status", "evidence"],
            "quote_automation": ["sample_id", "project_id", "quote_no", "quote_date", "customer", "item", "material", "capacity", "quantity", "amount", "source_file", "annotation_status", "evidence"],
        },
        "samples": [*cad_samples, *quote_samples],
        "coverage": {"cad_files": cad_total, "cad_project_linked": cad_linked, "structured_drawings": len(status_rows), "cad_readable": status_ok, "cad_read_fail": status_failed, "design_attribute_rows": len(design_rows), "part_rows": len(part_rows), "nozzle_rows": len(nozzle_rows), "drawings_with_tables": table_rows, "quote_rows": 162, "relevant_priced_quotes": priced_relevant, "issued_priced_quotes": issued_priced},
        "readiness": {
            "cad_object_recognition": {"level": "시드 구축", "score": round(status_ok / len(status_rows) * 100, 1) if status_rows else 0, "basis": "구조화 도면 중 정상 해독 비율. 객체 라벨·좌표 주석은 별도 검수 필요"},
            "quote_automation": {"level": "입력 필드 보강 필요", "score": round(issued_priced / priced_relevant * 100, 1) if priced_relevant else 0, "basis": "유효·금액 확인 견적 중 경동 발행 금액 비율. 품목 속성 정규화는 별도 필요"},
        },
        "gaps": [
            {"priority": "P0", "area": "CAD 라벨", "message": "객체별 bounding box/좌표, 표준 object_id, 사람이 검수한 라벨이 필요합니다."},
            {"priority": "P0", "area": "도면 속성", "message": "용량·재질·직경·높이·두께·설계압력·설계온도를 공통 단위와 코드로 정규화해야 합니다."},
            {"priority": "P1", "area": "견적 연결", "message": "견적 품목과 CAD 객체·BOM을 project_id와 line_item_id로 연결해야 합니다."},
            {"priority": "P1", "area": "금액 학습", "message": "견적 버전, 수주 여부, 실제 원가와 납기·변경 이력을 추가해야 합니다."},
            {"priority": "P2", "area": "검증 분할", "message": "사람 검수 후 고객·프로젝트 기준으로 train/validation/test를 분리해야 합니다."},
        ],
        "exclusions": ["원본 CAD 형상 자체를 임의 해석하지 않음", "구조화 추출값을 사람 검수 완료 라벨로 간주하지 않음", "수주 후 생성 정보는 견적 자동화 입력에서 제외"],
    }


def similar_projects(repo: Repository, project_id: str) -> list[dict[str, Any]]:
    target = repo.project(project_id.upper())
    if target is None:
        return []
    candidates = repo.projects()
    target_text = f"{target.get('item','')} {target.get('name','')}".casefold()
    target_tokens = set(target_text.replace("/", " ").split())
    ranked = []
    for item in candidates:
        if item["id"] == project_id.upper():
            continue
        tokens = set(f"{item.get('item','')} {item.get('name','')}".casefold().replace("/", " ").split())
        union = target_tokens | tokens
        score = len(target_tokens & tokens) / len(union) if union else 0
        if item.get("customer") == target.get("customer"):
            score += 0.2
        ranked.append({"project_id": item["id"], "name": item["name"], "customer": item["customer"],
                       "item": item["item"], "similarity": round(min(score, 1.0), 3)})
    return sorted(ranked, key=lambda row: row["similarity"], reverse=True)[:5]
