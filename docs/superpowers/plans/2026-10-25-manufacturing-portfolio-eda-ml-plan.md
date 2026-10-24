# 경동글로벌텍 제조 포트폴리오 및 EDA·ML 구현 계획

## 목표

기존 반응기 12건 대시보드를 전체 제조자료 약 31GB의 경영·생산 분석 대시보드로 확장한다. 전체 파일은 읽기 전용 메타데이터 원장에 포함하고, 금액 지표·EDA·ML은 근거가 확인된 반응기·견적·수주·도면 데이터로 제한한다.

설계 기준: `docs/superpowers/specs/2026-10-25-manufacturing-portfolio-eda-ml-design.md`

## 구현 원칙

- 테스트를 먼저 추가하고 가장 작은 구현으로 통과시킨다.
- 원본 폴더에는 어떤 파일도 쓰지 않는다.
- 최초 단계에서는 전체 파일의 메타데이터만 수집한다. 문서 본문 추출은 업무 관련 후보에만 수행한다.
- 기존 반응기 API와 화면을 깨지 않으면서 새 포트폴리오 API를 추가한다.
- 전체 스캔은 파일 단위 실패를 허용하고 진행 상태를 저장한다.
- ML 준비도 기준을 만족하지 않으면 모델 대신 진단 결과를 반환한다.

## 1. 구성과 데이터 루트 분리

### 수정 파일

- `dashboard/config.py`
- `.env.example`
- `README.md`
- `tests/test_config.py`

### 작업

1. `KYUNGDONG_DATA_ROOT`를 전체 `20261003 자료` 루트로 정의한다.
2. 기존 정제 반응기 경로는 전체 루트 아래 `반응기_리포지토리`로 자동 탐색하고, 필요 시 `KYUNGDONG_REACTOR_ROOT`로 재정의한다.
3. 전체 루트와 정제 루트의 필수 구조를 독립 검증한다.
4. 테스트 픽스처가 전체 루트와 정제 루트를 함께 만들도록 변경한다.

### 검증

```bash
uv run pytest tests/test_config.py -q
```

## 2. 전체 파일 원장 스키마와 증분 스캐너

### 생성·수정 파일

- `dashboard/schema.py`
- `dashboard/scanner.py`
- `dashboard/importer.py`
- `tests/test_scanner.py`

### 작업

1. 스키마 생성을 `schema.py`로 분리한다.
2. `sources`, `ingestion_runs`, `manufacturing_files`, `duplicate_groups`, `scan_errors` 테이블과 검색 인덱스를 추가한다.
3. 경로, 크기, 수정시각, 확장자, 연도 소스를 수집하는 순회 스캐너를 구현한다.
4. 실행 위험, 임시·백업, 미디어, CAD, 문서, 스프레드시트 분류기를 구현한다.
5. 경로·크기·수정시각이 같은 파일은 재처리하지 않고, 신규·변경 파일에만 해시를 계산한다.
6. 삭제된 원본은 레코드를 지우지 않고 `exists=0`으로 표시한다.
7. 스캔 결과와 오류 수를 `ingestion_runs`에 기록한다.

### 테스트

- 최초 스캔 파일 수 및 용량
- 재실행 멱등성
- 신규·변경·삭제 탐지
- 위험·임시 파일 격리
- 파일 오류 발생 시 나머지 스캔 지속

### 검증

```bash
uv run pytest tests/test_scanner.py -q
```

## 3. 프로젝트·고객·설비 후보 정규화

### 생성·수정 파일

- `dashboard/classifier.py`
- `dashboard/importer.py`
- `tests/test_classifier.py`

### 작업

1. Unicode NFC/NFD 차이를 정규화하되 원문 경로는 그대로 보존한다.
2. `KD25xx`, `KD26xx`, `GD25xx`, `GD26xx` 코드 후보 추출기를 구현한다.
3. 연도 폴더와 프로젝트 폴더에서 고객·설비 후보를 추출한다.
4. 설비 키워드를 반응기, 탱크, 열교환기, 교반기, 탈포기, 배관, 프레임, 기타로 분류한다.
5. 후보값과 신뢰도, 추출 근거를 저장한다.
6. 기존 `R01`~`R12` 정제 데이터와 KD/GD 코드를 우선 연결한다.
7. 충돌과 미분류를 `quality_issues`에 기록한다.

### 테스트

- 실제 폴더명 축약 샘플 분류
- 한 파일의 다중 프로젝트 연결
- 고객명 원문·정규화값 보존
- 불확실한 값의 `미분류` 처리

### 검증

```bash
uv run pytest tests/test_classifier.py -q
```

## 4. 경영·생산 데이터마트와 집계

### 생성·수정 파일

- `dashboard/portfolio.py`
- `dashboard/repository.py`
- `tests/test_portfolio.py`

### 작업

1. 프로젝트, 고객, 설비, 파일 자산을 위한 집계 쿼리를 구현한다.
2. 연도별 프로젝트·고객·자료 수와 용량을 계산한다.
3. 기존 견적·수주 데이터는 정제 반응기 소스를 우선 사용한다.
4. 확인된 계약·발주 금액만 수주 KPI에 포함한다.
5. 매출 견적, 매입 견적, 참고 견적과 변경 버전을 분리한다.
6. 고객·설비·연도별 추세와 최근 활동 집계를 구현한다.
7. 모든 금액 집계에 포함·제외 건수와 규칙을 반환한다.

### 테스트

- 수주·견적 기존 규칙 회귀
- 중복 견적 버전 합산 방지
- 연도·고객·설비별 합계
- 파일 전체 합계와 부분 합계 일치
- `미확인` 값이 0으로 계산되지 않음

### 검증

```bash
uv run pytest tests/test_dashboard.py tests/test_portfolio.py -q
```

## 5. 포트폴리오·파일·도면 API

### 수정 파일

- `dashboard/api.py`
- `dashboard/repository.py`
- `tests/test_api.py`

### 작업

1. 고객, 설비, 활동, 수주와 도면 분석 API를 추가한다.
2. 전체 파일 API에 연도·고객·프로젝트·설비·자료유형·확장자 필터와 페이지네이션을 추가한다.
3. 파일 열기는 색인된 업무 파일이면서 전체 허용 루트 아래에 있을 때만 허용한다.
4. 실행 위험·의심 HTML·임시 파일은 열기 요청을 거부한다.
5. 재색인 API가 증분 스캔 결과와 오류 요약을 반환하도록 변경한다.

### API

- `GET /api/portfolio/customers`
- `GET /api/portfolio/equipment`
- `GET /api/portfolio/activity`
- `GET /api/orders`
- `GET /api/drawings`
- 확장된 `GET /api/files`
- 확장된 `POST /api/admin/reindex`

### 검증

```bash
uv run pytest tests/test_api.py -q
```

## 6. EDA와 ML 준비도 서비스

### 생성·수정 파일

- `dashboard/analytics.py`
- `dashboard/api.py`
- `pyproject.toml`
- `tests/test_analytics.py`

### 작업

1. pandas와 scikit-learn을 분석 선택 의존성으로 추가한다.
2. 반응기 관련 유효 표본을 생성하는 단일 데이터셋 빌더를 구현한다.
3. 결측률, 범주 분포, 금액·도면 수 이상치와 전환 교차표를 생성한다.
4. 수주 이후 생성된 특성을 제외하는 누출 방지 목록을 적용한다.
5. 표본 수, 목표 분포와 시간 범위에 따른 ML 준비도 판정을 구현한다.
6. 유사 프로젝트는 표준화된 수치 특성과 범주 일치도를 조합해 제공한다.
7. 준비도 기준을 만족할 때만 기준 회귀·분류 모델을 교차검증한다.
8. 기준 모델 개선이 없거나 분할별 표본이 부족하면 모델 결과 대신 보강 권고를 반환한다.

### API

- `GET /api/analytics/eda`
- `GET /api/analytics/ml-readiness`
- `GET /api/analytics/similar-projects`

### 테스트

- 반응기 외 데이터 분석 제외
- 근거 없는 금액 제외
- 표본 부족 시 모델 미게시
- 시간 누출 특성 제외
- 동일 입력의 분석 결과 재현성

### 검증

```bash
uv run pytest tests/test_analytics.py -q
```

## 7. 프런트엔드 정보 구조 확장

### 생성·수정 파일

- `web/src/App.tsx`
- `web/src/api.ts`
- `web/src/styles.css`
- `web/src/components/PortfolioDashboard.tsx`
- `web/src/components/ProjectExplorer.tsx`
- `web/src/components/QuoteOrderAnalysis.tsx`
- `web/src/components/EquipmentDrawingAnalysis.tsx`
- `web/src/components/AssetExplorer.tsx`
- `web/src/components/AnalyticsWorkspace.tsx`

### 작업

1. 내비게이션을 경영 현황, 제조 프로젝트, 견적·수주 분석, 설비·도면 분석, 전체 자료, EDA·ML, 데이터 품질로 변경한다.
2. 기존 `App.tsx`의 화면 컴포넌트를 파일별로 분리한다.
3. 경영 화면에 연도·고객·설비별 KPI와 추세를 추가한다.
4. 전체 자료 화면에 서버 페이지네이션과 복합 필터를 추가한다.
5. EDA·ML 화면에 표본·제외 건수·기준일·준비도와 유사 프로젝트를 표시한다.
6. 수치마다 집계 규칙과 근거로 이동할 수 있는 상세 정보를 제공한다.
7. 로딩, 빈 결과, 부분 오류와 재색인 진행 상태를 구현한다.
8. 데스크톱과 태블릿에서 표와 필터가 잘리지 않도록 검증한다.

### 검증

```bash
cd web && npm run build
```

## 8. 실제 자료 적재와 데이터 품질 검토

### 생성·수정 파일

- `dashboard/__main__.py`
- `README.md`
- `.env.example`
- 필요 시 `docs/data-quality/2026-10-25-initial-scan.md`

### 작업

1. CLI에 `scan`, `reindex`, `analytics` 명령을 제공한다.
2. 실제 전체 자료를 메타데이터 우선 모드로 최초 적재한다.
3. 원본 폴더와 파일 수·용량을 대조한다.
4. 프로젝트 코드, 고객, 설비와 문서 유형별 대표 샘플을 검토한다.
5. 오분류 규칙을 수정하고 재색인한다.
6. 반응기 분석 표본과 제외 사유를 검토한다.
7. 초기 데이터 품질 보고서를 작성한다.

### 검증

```bash
uv run python -m dashboard scan
uv run python -m dashboard analytics
uv run pytest -q
```

## 9. 최종 통합 검증

1. 전체 백엔드 테스트를 실행한다.
2. 프런트엔드 프로덕션 빌드를 실행한다.
3. API 상태, 파일 수, 프로젝트 수와 주요 KPI를 확인한다.
4. 브라우저에서 모든 메뉴, 필터, 프로젝트 상세, EDA·ML 화면과 파일 열기를 점검한다.
5. 위험 파일 열기 차단과 경로 순회 방지를 확인한다.
6. 작업 전후 원본 파일 수·크기·수정시각이 변하지 않았는지 확인한다.

```bash
uv run pytest -q
cd web && npm run build
```

## 권장 실행 순서

1. 1~3단계로 안전한 전체 파일 원장과 분류 기반을 완성한다.
2. 4~5단계로 경영·생산 데이터마트와 API를 완성한다.
3. 6단계에서 EDA·ML 준비도를 구현한다.
4. 7단계에서 화면을 확장한다.
5. 8~9단계에서 실제 31GB 자료를 적재하고 품질을 보정한 뒤 통합 검증한다.

각 단계는 독립 테스트가 통과해야 다음 단계로 진행한다.
