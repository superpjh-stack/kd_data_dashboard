from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from dashboard.api import create_app


def fixture(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    (root / "bom/data").mkdir(parents=True)
    (root / "index").mkdir()
    cases = [
        {"id": "R01", "name": "테스트 반응기", "customer": "고객사", "item": "300L 반응기", "code": "KD-01", "status": "수주(계약)", "order": {"date": "2026-01-01", "amount": 10000000, "kind": "계약", "desc": "근거 확인"}, "notes": [], "counts": {"order": 1, "draw": 1, "quote": 1, "ref": 0}, "drawings": [], "parts": [], "quotes": []},
        {"id": "R12", "name": "참고", "customer": "참고사", "item": "플랜트", "code": "-", "status": "견적·참고", "order": None, "notes": [], "counts": {"order": 0, "draw": 0, "quote": 1, "ref": 1}, "drawings": [], "parts": [], "quotes": []},
    ]
    (root / "bom/data/cases_pipeline.json").write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    (root / "index/quotes.csv").write_text("건ID,견적일,견적번호,수신처,품명,합계금액(원),네고금액(원),VAT,발행구분,반응기관련,해당건견적,파일명,단위(시트/PDF),리포지토리경로,비고\nR01,2026-01-01,Q1,고객사,반응기,12000000,,VAT 별도,경동 발행,O,O,q.xlsx,시트,q.xlsx,\nR12,2026-01-02,Q2,참고사,전체 플랜트,999000000,,VAT 별도,경동 발행,O,O,r.xlsx,시트,r.xlsx,\n", encoding="utf-8")
    (root / "index/files.csv").write_text("건ID,건폴더,대분류,세부구분,파일명,확장자,크기(byte),수정일,리포지토리경로,원본경로,md5,본문텍스트\nR01,R01,01_수주,계약서,계약.pdf,.pdf,10,2026-01-01,계약.pdf,원본/계약.pdf,abc,O\n", encoding="utf-8")
    (root / "계약.pdf").write_bytes(b"test")
    return root


def test_summary_excludes_reference_plant_quote(tmp_path: Path):
    root = fixture(tmp_path)
    with TestClient(create_app(root, tmp_path / "test.sqlite3")) as client:
        result = client.get("/api/dashboard/summary")
        assert result.status_code == 200
        assert result.json()["kpis"]["order_amount"] == 10000000
        assert result.json()["kpis"]["quote_amount"] == 12000000


def test_project_and_safe_file_access(tmp_path: Path):
    root = fixture(tmp_path)
    with TestClient(create_app(root, tmp_path / "test.sqlite3")) as client:
        assert client.get("/api/projects/R01").status_code == 200
        assert client.get("/api/projects/UNKNOWN").status_code == 404
        assert client.get("/api/files/1/open").status_code == 200
        assert client.get("/api/files/999/open").status_code == 404


def test_portfolio_and_analytics_endpoints(tmp_path: Path):
    root = fixture(tmp_path)
    extra = root / "26 경동도면함" / "KD2601 고객 반응기"
    extra.mkdir(parents=True)
    (extra / "KD2601-01 제작도.dwg").write_bytes(b"drawing")
    (extra / "setup.exe").write_bytes(b"unsafe")
    with TestClient(create_app(root, tmp_path / "test.sqlite3")) as client:
        portfolio = client.get("/api/portfolio/summary")
        assert portfolio.status_code == 200
        assert portfolio.json()["files"] >= 6
        assets = client.get("/api/manufacturing-files?classification=도면·CAD").json()
        assert assets["total"] == 1
        assert client.get(f"/api/manufacturing-files/{assets['items'][0]['id']}/open").status_code == 200
        risky = client.get("/api/manufacturing-files?classification=격리").json()["items"][0]
        assert client.get(f"/api/manufacturing-files/{risky['id']}/open").status_code == 404
        report = client.get("/api/analytics/ml-readiness").json()
        assert report["model_published"] is False
        assert report["tasks"]["quote_range"]["ready"] is False
