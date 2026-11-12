import json
import sqlite3
from pathlib import Path
from fastapi.testclient import TestClient
from dashboard.api import create_app
from dashboard.importer import SCHEMA
from dashboard.classifier import source_year


def test_selected_sources_survive_restart_without_legacy_data(tmp_path: Path):
    source = tmp_path / 'data'
    folder = source / '19년 도면함' / 'GD1901 반응기'
    folder.mkdir(parents=True)
    (folder / 'a.dwg').write_bytes(b'AC1032new')
    history = source / 'History'
    history.mkdir()
    (history / 'old.dwg').write_bytes(b'old')
    db = tmp_path / 'data.sqlite3'
    with sqlite3.connect(db) as con:
        con.executescript(SCHEMA)
        con.execute("INSERT INTO files(project_id,filename) VALUES('R01','old.pdf')")
    for _ in range(2):
        with TestClient(create_app(source, db)) as client:
            assert client.get('/api/files').json()['items'] == []
            assert client.get('/api/portfolio/summary').json()['files'] == 1
            files = client.get('/api/manufacturing-files').json()['items']
            assert files[0]['source_year'] == 2019
            assert client.get(f"/api/manufacturing-files/{files[0]['id']}/open").content == b'AC1032new'
            assert client.get('/api/dashboard/summary').json()['kpis']['order_amount'] is None
            assert client.get('/api/analytics/ml-readiness').json()['ready'] is False
            golden = client.get('/api/analytics/golden-dataset').json()
            assert golden['coverage']['cad_files'] == 1
            assert golden['coverage']['quote_rows'] == 0
            assert golden['readiness']['cad_object_recognition']['score'] == 0
            assert client.post('/api/admin/reindex').json()['manufacturing_files'] == 1
    with sqlite3.connect(db) as con:
        assert con.execute('SELECT COUNT(*) FROM files').fetchone()[0] == 0
        assert con.execute('SELECT sha256 FROM manufacturing_files').fetchone()[0]


def test_year_formats():
    assert source_year(Path('26년 도면함/a.dwg')) == 2026
    assert source_year(Path('26 경동도면함/a.dwg')) == 2026
