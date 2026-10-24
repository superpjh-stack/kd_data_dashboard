from __future__ import annotations

import os
from pathlib import Path


def data_root() -> Path:
    value = os.getenv("KYUNGDONG_DATA_ROOT", "").strip()
    if not value:
        raise RuntimeError("KYUNGDONG_DATA_ROOT 환경변수에 20261003 자료 경로를 지정하세요.")
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise RuntimeError(f"전체 제조자료 경로가 없습니다: {root}")
    return root


def reactor_root(root: Path | None = None) -> Path:
    configured = os.getenv("KYUNGDONG_REACTOR_ROOT", "").strip()
    base = (root or data_root()).resolve()
    direct = base / "bom/data/cases_pipeline.json"
    candidate = Path(configured).expanduser().resolve() if configured else (base if direct.is_file() else base / "반응기_리포지토리")
    candidate = candidate.resolve()
    required = [candidate / "bom/data/cases_pipeline.json", candidate / "index/files.csv", candidate / "index/quotes.csv"]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"필수 색인 파일이 없습니다: {', '.join(missing)}")
    return candidate


def db_path() -> Path:
    path = Path(os.getenv("KYUNGDONG_DB_PATH", ".runtime/kyungdong.sqlite3")).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
