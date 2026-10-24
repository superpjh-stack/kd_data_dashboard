#!/bin/zsh
set -e
cd "${0:A:h}"
DEFAULT_DATA_ROOT='/Users/gerardo92/Desktop/01 경동글로벌텍 제조AI 플랫폼 구축 프로젝트/01 경동Data/20261003 자료'
export KYUNGDONG_DATA_ROOT="${KYUNGDONG_DATA_ROOT:-$DEFAULT_DATA_ROOT}"
if [[ ! -d "$KYUNGDONG_DATA_ROOT" ]]; then
  echo "반응기_리포지토리 경로를 찾을 수 없습니다:"
  echo "$KYUNGDONG_DATA_ROOT"
  echo '다른 위치라면 KYUNGDONG_DATA_ROOT 환경변수로 지정하세요.'
  exit 1
fi
trap 'kill 0' EXIT INT TERM
export UV_CACHE_DIR="${TMPDIR:-/tmp}/kyungdong-uv-cache"
uv run uvicorn dashboard.run:app --host 127.0.0.1 --port 8021 --reload &
(cd web && npm run dev) &
open http://127.0.0.1:5178/
wait
