"""Evidence and readiness for the selected 2019–2026 drawing collection."""
import json
from . import foundation


def active(repo):
    with repo.connect() as con:
        row = con.execute("SELECT value FROM meta WHERE key='dataset_mode'").fetchone()
    return bool(row and row[0] == 'selected_drawings')


def eda(repo):
    f = foundation.summary(repo.db)
    with repo.connect() as con:
        counts = con.execute("SELECT COUNT(*),COUNT(DISTINCT sha256),COUNT(DISTINCT project_code) FROM manufacturing_files WHERE exists_flag=1 AND classification='도면·CAD'").fetchone()
    return {'scope': '2019~2026 DWG 도면·기초데이터 입력양식',
            'samples': {'projects': counts[2], 'drawings': counts[0], 'unique_drawings': counts[1], 'quotes': f['analytics']['quote_rows'], 'priced_quotes': f['analytics']['quote_amount_rows'], 'actual_cost': f['analytics']['actual_cost_rows'], 'approved_gold': 0},
            'excluded': {'duplicate_copies': counts[0] - counts[1]},
            'order_amount': {'min': None, 'max': None, 'median': None}, 'timeline': [], 'drawing_activity': [],
            'rules': ['프로젝트·설비는 경로 기반 후보이며 업무 확정값이 아님', '도면 연도는 보관 폴더 연도', '자동 추출은 검수 완료 라벨이 아님', '견적 금액은 실제 원가나 수주액이 아님']}


def readiness(repo):
    return {'ready': False, 'model_published': False,
            'tasks': {key: {'ready': False, 'samples': 0} for key in ('drawing_attributes', 'cad_objects', 'quote_range', 'conversion')},
            'recommendations': ['1순위: 중복 제거 도면에서 속성 추출·유사도면 검색용 검수셋 구축', '2순위: 부품·노즐별 객체 핸들, 좌표, 정답 라벨 검수', '3순위: 견적 버전·품목·단위·공급범위 정규화 및 원본 견적 확보', '실제 원가·중량·수주 결과를 추가 확보; 빈 수주 결과를 미수주로 간주하지 않음', '동일 프로젝트·개정도면·중복 파일을 같은 분할에 배치하고 과거→미래 평가'],
            'leakage_excluded': ['견적일 이후 도면', '최종 수주상태', '실제원가', '금액이 포함된 메모']}


def golden(repo):
    f = foundation.summary(repo.db)
    with repo.connect() as con:
        counts = con.execute("SELECT COUNT(*),COUNT(DISTINCT sha256),SUM(project_code IS NOT NULL) FROM manufacturing_files WHERE exists_flag=1 AND classification='도면·CAD'").fetchone()
        has_analysis = con.execute("SELECT 1 FROM sqlite_master WHERE name='analysis_drawings'").fetchone()
        statuses, text_count, samples = {}, 0, []
        if has_analysis:
            active_hashes = "SELECT DISTINCT sha256 FROM manufacturing_files WHERE exists_flag=1 AND classification='도면·CAD'"
            statuses = dict(con.execute(f"SELECT parse_status,COUNT(*) FROM analysis_drawings WHERE sha256 IN ({active_hashes}) GROUP BY parse_status"))
            text_count = con.execute(f"SELECT COALESCE(SUM(text_count),0) FROM analysis_drawings WHERE sha256 IN ({active_hashes})").fetchone()[0]
            rows = con.execute(f"SELECT t.*,d.source_paths_json FROM analysis_drawing_texts t JOIN analysis_drawings d USING(sha256) WHERE d.parse_status='parsed' AND t.sha256 IN ({active_hashes}) LIMIT 3").fetchall()
            samples = [{'sample_id': f"{r['sha256']}:{r['ordinal']}", 'task': 'CAD 문자 추출', 'project_id': None, 'source_file': json.loads(r['source_paths_json'])[0], 'object_label': r['entity_type'], 'spec': r['text_value'], 'annotation_status': '자동 추출·미검수', 'evidence': f"{json.loads(r['source_paths_json'])[0]} · handle={r['handle_json']} · point={r['point_json']}"} for r in rows]
        proposal = con.execute("SELECT value FROM meta WHERE key='golden_proposal'").fetchone()
    quotes = foundation.records(repo.db, sheet='21_견적이력', limit=5)['items']
    for r in quotes:
        v = r['values']
        samples.append({'sample_id': f"foundation:21:{r['source_row']}", 'task': '견적금액 후보', 'project_id': v.get('C'), 'quote_no': v.get('A'), 'customer': v.get('E'), 'amount': v.get('K'), 'annotation_status': '입력양식·미검수', 'evidence': f"21_견적이력!K{r['source_row']} · SHA256={f['source']['sha256']}"})
    return {'title': '새 자료 기반 골든데이터셋 후보', 'purpose': '도면 속성·객체인식·견적금액의 검수 가능한 후보. 승인된 학습 정답은 0건입니다.', 'status': 'candidate_only',
            'schema': {'cad_object': ['drawing_id', 'revision', 'object_id', 'entity_handles', 'class_label', 'bbox_or_polygon', 'unit', 'reviewer'], 'quote_automation': ['quote_no', 'revision', 'line_item_id', 'quote_date', 'drawing_revision_at_quote', 'quantity', 'material', 'weight_kg', 'amount', 'vat_basis', 'supply_scope', 'source_cell', 'reviewer']},
            'samples': samples, 'coverage': {'cad_files': counts[0], 'unique_cad_files': counts[1], 'duplicate_copies': counts[0]-counts[1], 'cad_project_linked': counts[2] or 0, 'structured_drawings': sum(statuses.values()), 'cad_readable': statuses.get('parsed', 0), 'cad_read_fail': statuses.get('failed', 0), 'cad_partial': statuses.get('partial', 0), 'text_entities': text_count, 'part_rows': 0, 'nozzle_rows': 0, 'quote_rows': f['analytics']['quote_rows'], 'relevant_priced_quotes': f['analytics']['quote_amount_rows'], 'issued_priced_quotes': f['analytics']['quote_amount_rows']},
            'readiness': {'cad_object_recognition': {'level': '사람 검수 필요', 'score': 0, 'basis': '검수 완료 정답 0건. 해석 성공률을 ML 준비도로 사용하지 않음'}, 'quote_automation': {'level': '연결·속성 보강 필요', 'score': 0, 'basis': '금액 입력과 학습 가능 여부는 별도. 실제 원가 없음'}},
            'gaps': [{'priority': 'P0', 'area': '도면 연결', 'message': '도면번호·Rev·수주·견적 품목을 확인하고 PDF 참조와 DWG 원본을 연결'}, {'priority': 'P0', 'area': '라벨', 'message': '재질·용량·압력·온도·객체 좌표를 원본과 대조하여 검수'}, {'priority': 'P1', 'area': '견적', 'message': '견적 원본, 공급범위, VAT, 중량, 실제원가, 수주 결과 확보'}, {'priority': 'P1', 'area': '분할', 'message': '프로젝트·개정·중복 그룹을 유지하고 시간순 평가'}],
            'proposal': json.loads(proposal[0]) if proposal else None}
