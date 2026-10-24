# 경동글로벌텍 제조 데이터 대시보드

전체 제조자료의 연도·고객·프로젝트·설비 현황과 반응기 수주·견적·도면 분석을 연결한 React + FastAPI 대시보드입니다. 원본 `20261003 자료`는 읽기 전용으로 사용합니다.

## 실행

Python 3.11+, Node 22+, `uv`가 필요합니다.

```bash
export KYUNGDONG_DATA_ROOT="/절대경로/20261003 자료"
uv sync --extra dev
cd web && npm install && cd ..
./start-dev.command
```

현재 Mac에서는 `start-dev.command`에 경동 반응기 저장소 경로가 기본값으로 설정되어 있어 환경변수 없이 실행할 수 있습니다. 데이터 위치가 바뀐 경우에만 `KYUNGDONG_DATA_ROOT`로 덮어쓰면 됩니다.

브라우저에서 `http://127.0.0.1:5178`을 엽니다. API는 `http://127.0.0.1:8021`입니다.

프로덕션 정적 빌드:

```bash
cd web && npm run build && cd ..
export KYUNGDONG_DATA_ROOT="/절대경로/20261003 자료"
uv run uvicorn dashboard.run:app --host 127.0.0.1 --port 8021
```

## 검증

```bash
uv run pytest
cd web && npm run build
```

전체 자료를 명시적으로 재색인하거나 EDA·ML 준비도를 확인할 수 있습니다.

```bash
uv run python -m dashboard scan
uv run python -m dashboard analytics
```

## 데이터 기준

- 프로젝트·설계·BOM: `bom/data/cases_pipeline.json`
- 문서: `index/files.csv`
- 견적: `index/quotes.csv`
- 전체 제조자료: `25 경동도면함`, `26 경동도면함`과 `반응기_리포지토리`
- EDA·ML: 반응기·견적·수주·도면 관련 유효 표본만 사용
- 수주액: 계약·고객 발주 금액이 확인된 건만 포함
- 유효 견적액: `해당건견적=O`, `경동 발행`, R12 전체 플랜트 견적 제외

공개 네트워크에 배포하기 전에는 인증, TLS, 감사 로그를 추가해야 합니다.
