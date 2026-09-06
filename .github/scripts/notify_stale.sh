#!/usr/bin/env bash
# freshness 워크플로의 알림부. 열린 알림이 이미 있으면 중복 생성하지 않고,
# 갱신이 돌아오면 그 이슈를 닫는다.
set -euo pipefail

LABEL="dashboard-stale"
REPORT="report.txt"

gh label create "$LABEL" --color B60205 \
  --description "docs/index.html 갱신 정지 또는 무결성 실패" >/dev/null 2>&1 || true

open_issue=$(gh issue list --label "$LABEL" --state open --limit 1 \
  --json number --jq '.[0].number // empty')

run_url="$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID"

if [ "${STALE:-false}" = "true" ]; then
  if [ -n "$open_issue" ]; then
    echo "이미 열린 알림 #$open_issue — 중복 생성하지 않음"
    exit 0
  fi
  {
    echo "예약 검사에서 \`docs/index.html\` 이 기준(${MAX_AGE}시간)을 넘겨 갱신되지 않았거나 검사에 실패했습니다."
    echo
    echo '```'
    cat "$REPORT"
    echo '```'
    echo
    echo "로컬 생성 스크립트가 살아 있는지 먼저 확인하세요. 갱신이 돌아오면 이 이슈는 자동으로 닫힙니다."
    echo
    echo "[검사 로그]($run_url)"
  } > issue_body.md
  gh issue create --title "대시보드 갱신 정지 의심 — docs/index.html" \
    --label "$LABEL" --body-file issue_body.md
else
  if [ -n "$open_issue" ]; then
    gh issue comment "$open_issue" --body "갱신이 돌아왔습니다. 자동으로 닫습니다. [검사 로그]($run_url)"
    gh issue close "$open_issue" --reason completed
    echo "#$open_issue 닫음"
  else
    echo "이상 없음"
  fi
fi
