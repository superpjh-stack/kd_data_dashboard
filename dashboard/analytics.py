from __future__ import annotations

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
