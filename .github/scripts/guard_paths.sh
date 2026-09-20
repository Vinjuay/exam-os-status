#!/usr/bin/env bash
# 커밋 경로 가드 — public 저장소에 docs/ 밖 파일(스크립트·config.json·logs·백업)이
# 실수로 강제 추가되는 것을 CI에서 막는다. .gitignore는 강제 add를 막지 못한다.
set -euo pipefail

ALLOWED='^(docs/|\.github/|\.gitignore$)'
range="${1:-}"

# core.quotepath=false 가 없으면 한글 파일명이 "docs/ANKI_\354\240\225..." 처럼
# 따옴표로 감싸여 octal 로 escape 되어 나온다. 그러면 ^docs/ 앵커가 여는 따옴표에
# 막혀, docs/ 안의 파일이 「허용 경로 밖」으로 오판된다(2026-09-20 실측).
# docs/ 는 이미 한글 파일명을 쓰고 있으므로 가드 쪽을 고친다.
git_q() { git -c core.quotepath=false "$@"; }

if [ -n "$range" ]; then
  files=$(git_q diff --name-only "$range")
elif git rev-parse --verify -q HEAD~1 >/dev/null; then
  files=$(git_q diff --name-only HEAD~1 HEAD)
else
  files=$(git_q ls-files)
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
