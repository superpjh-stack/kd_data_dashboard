from pathlib import Path
import sqlite3

from dashboard.classifier import customer_candidate, equipment_type, file_class, project_codes, project_label
from dashboard.scanner import scan_files


def test_classifier_extracts_project_and_safety():
    assert project_codes("26 경동도면함/KD2600-18 유엠씨 반응기/도면.dwg") == ["KD2600-18"]
    assert equipment_type("300L REACTOR 제작도")[0] == "반응기"
    assert file_class(Path("setup.exe")) == ("격리", False)
    assert file_class(Path("drawing.dwg")) == ("도면·CAD", True)
    assert project_label(Path("26 경동도면함/KD2601 고객사 반응기/도면.dwg"), "KD2601") == "고객사 반응기"
    assert customer_candidate("고객사 반응기")[0] == "고객사 반응기"


def test_incremental_scan_tracks_changes_and_missing(tmp_path: Path):
    root = tmp_path / "data"
    folder = root / "26 경동도면함" / "KD2601 고객 반응기"
    folder.mkdir(parents=True)
    drawing = folder / "KD2601-01 제작도.dwg"
    drawing.write_bytes(b"drawing")
    (folder / "tool.exe").write_bytes(b"unsafe")
    db = tmp_path / "scan.sqlite3"

    first = scan_files(root, db)
    second = scan_files(root, db)
    assert first["scanned"] == 2
    assert first["changed"] == 2
    assert second["changed"] == 0

    drawing.unlink()
    third = scan_files(root, db)
    assert third["missing"] == 1
    with sqlite3.connect(db) as con:
        risky = con.execute("SELECT open_allowed FROM manufacturing_files WHERE filename='tool.exe'").fetchone()
    assert risky == (0,)
