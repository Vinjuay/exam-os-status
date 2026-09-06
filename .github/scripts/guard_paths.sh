#!/usr/bin/env bash
# 커밋 경로 가드 — public 저장소에 docs/ 밖 파일(스크립트·config.json·logs·백업)이
# 실수로 강제 추가되는 것을 CI에서 막는다. .gitignore는 강제 add를 막지 못한다.
set -euo pipefail

ALLOWED='^(docs/|\.github/|\.gitignore$)'
range="${1:-}"

if [ -n "$range" ]; then
  files=$(git diff --name-only "$range")
elif git rev-parse --verify -q HEAD~1 >/dev/null; then
  files=$(git diff --name-only HEAD~1 HEAD)
else
  files=$(git ls-files)
fi

if [ -z "$files" ]; then
  echo "변경 파일 없음"
  exit 0
fi

echo "검사 대상:"
echo "$files" | sed 's/^/  /'

violations=$(echo "$files" | grep -Ev "$ALLOWED" || true)
if [ -n "$violations" ]; then
  echo
  echo "허용 경로(docs/, .github/, .gitignore) 밖의 파일이 커밋되었습니다:" >&2
  echo "$violations" | sed 's/^/  - /' >&2
  echo >&2
  echo "생성 스크립트·config.json·logs·백업은 로컬에만 두어야 합니다." >&2
  exit 1
fi

echo
echo "통과 — 허용 경로만 변경됨"
