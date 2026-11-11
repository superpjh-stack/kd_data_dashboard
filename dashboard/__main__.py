from __future__ import annotations

import argparse
import json
from pathlib import Path

import uvicorn

from .analytics import eda, ml_readiness
from .config import data_root, db_path, reactor_root
from .importer import rebuild_database
from .repository import Repository
from .foundation import import_workbook


def main() -> None:
    parser = argparse.ArgumentParser(description="경동글로벌텍 제조 데이터 대시보드")
    parser.add_argument("command", nargs="?", choices=("serve", "scan", "analytics", "import-foundation"), default="serve")
    parser.add_argument("--workbook", type=Path, help="경동 기초데이터 입력양식 xlsx")
    args = parser.parse_args()
    if args.command == "import-foundation":
        if args.workbook is None:
            parser.error("import-foundation에는 --workbook 경로가 필요합니다.")
        print(json.dumps(import_workbook(args.workbook, db_path()), ensure_ascii=False, indent=2))
        return
    root = data_root()
    reactor = reactor_root(root)
    database = db_path()
    if args.command == "serve":
        uvicorn.run("dashboard.run:app", host="127.0.0.1", port=8021, reload=False)
        return
    result = rebuild_database(reactor, database, root)
    if args.command == "scan":
        print(result)
        return
    repo = Repository(database, reactor, root)
    print({"eda": eda(repo), "ml_readiness": ml_readiness(repo)})


if __name__ == "__main__":
    main()
