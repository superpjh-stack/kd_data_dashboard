from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import data_root, db_path, reactor_root
from .importer import rebuild_database
from .repository import Repository
from .analytics import eda, ml_readiness, similar_projects


def create_app(root: Path | None = None, db: Path | None = None) -> FastAPI:
    source = (root or data_root()).resolve()
    reactor = reactor_root(source)
    database = (db or db_path()).resolve()
    repo = Repository(database, reactor, source)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        rebuild_database(reactor, database, source)
        yield

    app = FastAPI(title="경동글로벌텍 반응기 데이터 대시보드", version="0.1.0", lifespan=lifespan)
    app.state.repo = repo

    @app.get("/api/health")
    def health():
        try:
            count = len(repo.projects())
            return {"status": "ok", "projects": count, "data_root": str(source)}
        except Exception as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.get("/api/dashboard/summary")
    def dashboard_summary():
        return repo.summary()

    @app.get("/api/projects")
    def projects(q: str = "", status: str = ""):
        return {"items": repo.projects(q, status)}

    @app.get("/api/projects/{project_id}")
    def project(project_id: str):
        value = repo.project(project_id.upper())
        if value is None:
            raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")
        return value

    @app.get("/api/quotes")
    def quotes(q: str = "", issuer: str = "", relevant_only: bool = False):
        return {"items": repo.quotes(q, issuer, relevant_only)}

    @app.get("/api/files")
    def files(q: str = "", category: str = "", extension: str = "", project_id: str = ""):
        return {"items": repo.files(q, category, extension, project_id)}

    @app.get("/api/quality/issues")
    def quality():
        return {"items": [*repo.portfolio_quality(), *repo.quality()]}

    @app.get("/api/portfolio/summary")
    def portfolio_summary():
        return repo.portfolio_summary()

    @app.get("/api/portfolio/customers")
    def portfolio_customers():
        return {"items": repo.portfolio_customers()}

    @app.get("/api/portfolio/equipment")
    def portfolio_equipment():
        return {"items": repo.portfolio_summary()["equipment"]}

    @app.get("/api/portfolio/activity")
    def portfolio_activity():
        return {"items": repo.portfolio_activity()}

    @app.get("/api/manufacturing-files")
    def manufacturing_files(q: str = "", year: str = "", classification: str = "", equipment: str = "",
                            project_code: str = "", limit: int = 100, offset: int = 0):
        if limit < 1 or limit > 500 or offset < 0:
            raise HTTPException(422, "limit은 1~500, offset은 0 이상이어야 합니다.")
        return repo.manufacturing_files(q, year, classification, equipment, project_code, limit, offset)

    @app.get("/api/drawings")
    def drawings():
        return {"items": repo.drawings()}

    @app.get("/api/analytics/eda")
    def analytics_eda():
        return eda(repo)

    @app.get("/api/analytics/ml-readiness")
    def analytics_ml_readiness():
        return ml_readiness(repo)

    @app.get("/api/analytics/similar-projects")
    def analytics_similar_projects(project_id: str):
        items = similar_projects(repo, project_id)
        if not items and repo.project(project_id.upper()) is None:
            raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")
        return {"items": items}

    @app.post("/api/admin/reindex")
    def reindex():
        return rebuild_database(reactor, database, source)

    @app.get("/api/files/{file_id}/open")
    def open_file(file_id: int):
        if file_id < 1:
            raise HTTPException(422, "파일 ID는 1 이상이어야 합니다.")
        path = repo.resolve_file(file_id)
        if path is None:
            raise HTTPException(404, "원본 파일을 찾을 수 없습니다.")
        return FileResponse(path, filename=path.name)

    @app.get("/api/manufacturing-files/{file_id}/open")
    def open_manufacturing_file(file_id: int):
        if file_id < 1:
            raise HTTPException(422, "파일 ID는 1 이상이어야 합니다.")
        path = repo.resolve_manufacturing_file(file_id)
        if path is None:
            raise HTTPException(404, "원본 파일을 찾을 수 없거나 열기가 허용되지 않습니다.")
        return FileResponse(path, filename=path.name)

    dist = Path(__file__).parent.parent / "web/dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    return app
