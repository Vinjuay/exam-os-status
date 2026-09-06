#!/usr/bin/env python3
"""refresh 커밋 메시지를 지표로 채운다.

`dashboard: refresh docs/index.html` 열댓 개는 로그로서 값이 0이다. 같은 자리에
그날의 숫자와 직전 대비 변화를 넣으면 `git log`가 그대로 일지가 된다.

노트북 생성 스크립트에서 (cmd 한글 깨짐을 피하려면 파일 경유가 안전하다):
    python .github/scripts/commit_message.py --out .git/COMMIT_MSG_dashboard
    git commit -F .git/COMMIT_MSG_dashboard

출력 예:
    dashboard: D-74 · 완료 214 · 적체 12/40 · 미코딩 113

    - 적체 12 → 14
    - 회수율 11.4% → 12.9%
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_metrics import extract  # noqa: E402

PAGE = "docs/index.html"
FALLBACK = "dashboard: refresh docs/index.html"

# 제목에 세울 지표 — 그날 판단에 쓰이는 네 개만. 순서가 곧 표시 순서다.
HEADLINE = [
    ("D-day", "D-{}", lambda m: m.get("dday")),
    ("주간 완료문항", "완료 {}", lambda m: (m.get("throughput") or {}).get("week_items")),
    ("예제 적체", "적체 {}", lambda m: _fraction(m, "queue", "backlog", "base")),
    ("미코딩", "미코딩 {}", lambda m: (m.get("errorlog") or {}).get("uncoded")),
]

# 본문에 「이전 → 현재」로 적을 지표. 변한 것만 나온다.
TRACKED = [
    ("적체", lambda m: (m.get("queue") or {}).get("backlog"), ""),
    ("1차 대기", lambda m: (m.get("queue") or {}).get("wait1"), ""),
    ("큐 밖", lambda m: (m.get("queue") or {}).get("outside"), ""),
    ("주간 완료문항", lambda m: (m.get("throughput") or {}).get("week_items"), ""),
    ("기록일", lambda m: (m.get("throughput") or {}).get("record_days"), ""),
    ("회수율", lambda m: (m.get("method") or {}).get("recovery_rate"), "%"),
    ("METHOD 등록", lambda m: (m.get("method") or {}).get("registered"), ""),
    ("미등록 후보", lambda m: (m.get("method") or {}).get("candidates"), ""),
    ("미코딩", lambda m: (m.get("errorlog") or {}).get("uncoded"), ""),
    ("미판정", lambda m: (m.get("skills") or {}).get("unjudged"), ""),
    ("감쇠", lambda m: (m.get("skills") or {}).get("decayed"), ""),
]


def _fraction(metrics: dict, section: str, num: str, den: str):
    part = metrics.get(section) or {}
    a, b = part.get(num), part.get(den)
    if a is None:
        return None
    return f"{a}/{b}" if b is not None else a


def previous_page(ref: str = "HEAD") -> str | None:
    """직전 커밋에 담긴 페이지. 첫 커밋이면 비교 대상이 없다."""
    try:
        return subprocess.run(["git", "show", f"{ref}:{PAGE}"], check=True,
                              capture_output=True, text=True).stdout
    except subprocess.CalledProcessError:
        return None


def score_changes(before: dict, after: dict) -> list[str]:
    lines = []
    for label, get, unit in TRACKED:
        old, new = get(before), get(after)
        if old == new or new is None:
            continue
        if old is None:      # 그 모듈이 없던 판에서 새로 생긴 지표
            lines.append(f"- {label} 신규 {new}{unit}")
        else:
            lines.append(f"- {label} {old}{unit} → {new}{unit}")
    return lines


def build(current_html: str, previous_html: str | None) -> str:
    now = extract(current_html)

    parts = [tpl.format(val) for _, tpl, get in HEADLINE
             if (val := get(now)) is not None]
    if not parts:
        # 네 지표를 하나도 못 읽었다 = 규격이 바뀌었거나 페이지가 깨졌다.
        # 커밋은 나가야 하므로 막지 않되, 로그에 그 사실을 남긴다.
        return FALLBACK + " (지표 판독 실패)"
    subject = "dashboard: " + " · ".join(parts)

    if previous_html is None:
        return subject

    changes = score_changes(extract(previous_html), now)
    if not changes:
        # 지표가 그대로면 그렇다고 적는다 — 로그를 읽는 쪽이 훑고 지나갈 수 있다.
        return subject + " (지표 변화 없음)"
    return subject + "\n\n" + "\n".join(changes)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=PAGE, type=Path)
    ap.add_argument("--previous", type=Path, default=None,
                    help="비교 기준 파일 (기본: git HEAD의 docs/index.html)")
    ap.add_argument("--ref", default="HEAD", help="비교 기준 커밋 (기본 HEAD)")
    ap.add_argument("--out", type=Path, default=None,
                    help="메시지를 UTF-8 파일로 쓴다 (git commit -F 용)")
    ap.add_argument("--check", action="store_true",
                    help="제목 지표를 전부 읽을 수 있는지만 확인하고 끝낸다 (CI용)")
    args = ap.parse_args()

    try:
        current = args.path.read_text(encoding="utf-8")
        previous = (args.previous.read_text(encoding="utf-8") if args.previous
                    else previous_page(args.ref))
        message = build(current, previous)
    except Exception as e:  # 배포를 멈추게 하지 않는다 — 메시지는 거들 뿐이다
        print(f"커밋 메시지 생성 실패: {e}", file=sys.stderr)
        message = FALLBACK

    if args.check:
        metrics = extract(args.path.read_text(encoding="utf-8"))
        missing = [label for label, _, get in HEADLINE if get(metrics) is None]
        if missing:
            print("제목 지표를 읽지 못했습니다: " + ", ".join(missing), file=sys.stderr)
            return 1
        print("통과 — 제목 지표 4종 전부 판독됨: " + message.splitlines()[0])
        return 0

    if args.out:
        args.out.write_text(message + "\n", encoding="utf-8")
    else:
        print(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
