from __future__ import annotations

import re
import unicodedata
from pathlib import Path


PROJECT_CODE = re.compile(r"\b(?:KD|GD)\s*[-_]?\s*(?:25|26)\d{2}(?:\s*[-_]\s*\d{1,2})?\b", re.I)

RISKY_EXTENSIONS = {".exe", ".dll", ".cab", ".ocx", ".tlb", ".com", ".bat"}
TEMP_EXTENSIONS = {".bak", ".tmp", ".dwl", ".dwl2", ".log", ".crdownload"}
MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".avif", ".mp4", ".wmv"}
CAD_EXTENSIONS = {".dwg", ".cad", ".dxf", ".step", ".stp", ".ipt", ".iam", ".sldprt", ".sldasm", ".x_t", ".sat", ".igs"}
SHEET_EXTENSIONS = {".xlsx", ".xls", ".xlsm", ".csv"}
DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".doc", ".hwp", ".hwpx", ".pptx", ".ppt", ".eml", ".txt"}

EQUIPMENT_TERMS = {
    "반응기": ("반응기", "reactor"),
    "탱크": ("탱크", "tank", "저장조", "저장탱크"),
    "열교환기": ("열교환", "heat exchanger"),
    "교반기": ("교반", "agitator", "impeller"),
    "탈포기": ("탈포",),
    "배관": ("배관", "piping", "pipe"),
    "프레임": ("프레임", "frame"),
}


def normalized(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def project_codes(value: str) -> list[str]:
    result = []
    for match in PROJECT_CODE.findall(normalized(value)):
        code = re.sub(r"[\s_]", "", match.upper()).replace("KD-", "KD").replace("GD-", "GD")
        code = re.sub(r"^(KD|GD)(\d{4})-(\d+)$", r"\1\2-\3", code)
        if code not in result:
            result.append(code)
    return result


def project_label(relative_path: Path, code: str) -> str:
    for part in relative_path.parts:
        clean = normalized(part)
        if Path(clean).suffix:
            continue
        if project_codes(clean) and code in project_codes(clean):
            label = PROJECT_CODE.sub("", clean).strip(" -_()[]")
            return re.sub(r"\s+", " ", label)
    return ""


def customer_candidate(label: str) -> tuple[str, float]:
    value = re.sub(r"\b(?:견적서|도면|사진|자료|발주서)\b", "", normalized(label), flags=re.I).strip(" -_")
    if not value or value in {"경동", "경동도면함"}:
        return "미분류", 0.0
    return value, 0.55


def equipment_type(value: str) -> tuple[str, float]:
    text = normalized(value).casefold()
    for category, terms in EQUIPMENT_TERMS.items():
        if any(term.casefold() in text for term in terms):
            return category, 0.8
    return "기타", 0.3


def file_class(path: Path) -> tuple[str, bool]:
    ext = path.suffix.casefold()
    if ext in RISKY_EXTENSIONS or ext in {".html", ".shtml"}:
        return "격리", False
    if ext in TEMP_EXTENSIONS or path.name == ".DS_Store":
        return "임시·백업", False
    if ext in MEDIA_EXTENSIONS:
        return "사진·영상", True
    if ext in CAD_EXTENSIONS:
        return "도면·CAD", True
    if ext in SHEET_EXTENSIONS:
        return "스프레드시트", True
    if ext in DOCUMENT_EXTENSIONS:
        return "문서", True
    return "기타", True


def source_year(relative_path: Path) -> int | None:
    top = normalized(relative_path.parts[0]) if relative_path.parts else ""
    if top.startswith("25 "):
        return 2025
    if top.startswith("26 "):
        return 2026
    return None
