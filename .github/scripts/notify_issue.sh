#!/usr/bin/env bash
# 감시 워크플로의 알림부 — 열린 알림이 있으면 중복 생성하지 않고,
# 상태가 정상으로 돌아오면 그 이슈를 닫는다. freshness·defects가 함께 쓴다.
#
# 환경변수: LABEL LABEL_COLOR LABEL_DESC TITLE REPORT BREACH INTRO [CLOSE_NOTE]
set -euo pipefail

: "${LABEL:?}" "${TITLE:?}" "${REPORT:?}" "${BREACH:?}" "${INTRO:?}"
LABEL_COLOR="${LABEL_COLOR:-B60205}"
LABEL_DESC="${LABEL_DESC:-$LABEL}"
CLOSE_NOTE="${CLOSE_NOTE:-정상으로 돌아왔습니다. 자동으로 닫습니다.}"

gh label create "$LABEL" --color "$LABEL_COLOR" --description "$LABEL_DESC" \
  >/dev/null 2>&1 || true

open_issue=$(gh issue list --label "$LABEL" --state open --limit 1 \
  --json number --jq '.[0].number // empty')

run_url="$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID"

if [ "$BREACH" = "true" ]; then
  if [ -n "$open_issue" ]; then
    echo "이미 열린 알림 #$open_issue — 중복 생성하지 않음"
    exit 0
  fi
  {
    echo "$INTRO"
    echo
    echo '```'
    cat "$REPORT"
    echo '```'
    echo
    echo "상태가 정상으로 돌아오면 이 이슈는 자동으로 닫힙니다."
    echo
    echo "[검사 로그]($run_url)"
  } > issue_body.md
  gh issue create --title "$TITLE" --label "$LABEL" --body-file issue_body.md
else
  if [ -n "$open_issue" ]; then
    gh issue comment "$open_issue" --body "$CLOSE_NOTE [검사 로그]($run_url)"
    gh issue close "$open_issue" --reason completed
    echo "#$open_issue 닫음"
  else
    echo "이상 없음"
  fi
fi
