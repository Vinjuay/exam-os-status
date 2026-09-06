#!/usr/bin/env python3
"""git history를 훑어 docs/index.html의 시계열 두 벌을 만든다.

- docs/history.ndjson       스냅샷 1건 = 1줄 (생성 시각 기준)
- docs/history-daily.ndjson 날짜 1일 = 1줄 (완료문항)

지표를 커밋할 때마다 덧붙이는 대신 매번 history 전체에서 다시 만든다.
그래서 결과가 멱등하고, 추출 규칙을 고치면 과거분까지 함께 교정된다.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_metrics import extract  # noqa: E402

PAGE = "docs/index.html"
SNAPSHOTS = Path("docs/history.ndjson")
DAILY = Path("docs/history-daily.ndjson")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True,
                          text=True).stdout


def commits() -> list[str]:
    """페이지를 건드린 커밋을 오래된 것부터."""
    out = git("log", "--reverse", "--format=%H", "--", PAGE)
    return [line for line in out.splitlines() if line]


def _changes_only(rows: list[dict]) -> list[dict]:
    """값이 그대로인 스냅샷은 버린다.

    페이지는 하루에도 열댓 번 다시 만들어지지만 지표는 대개 그대로다. 변한
    줄만 남기면 파일이 변경 이력이 되고, 해마다 수 MB씩 부는 일도 없다.
    맨 앞과 맨 끝은 계열의 시작과 현재 상태라 항상 남긴다.
    """
    kept: list[dict] = []
    last: dict | None = None
    for i, row in enumerate(rows):
        payload = {k: v for k, v in row.items() if k not in ("ts", "commit")}
        if last is None or payload != last or i == len(rows) - 1:
            kept.append(row)
            last = payload
    return kept


def build() -> tuple[list[dict], list[dict]]:
    snapshots: dict[str, dict] = {}   # 생성 시각 -> 레코드
    daily: dict[str, dict] = {}       # 날짜 -> 레코드

    for sha in commits():
        try:
            html = git("show", f"{sha}:{PAGE}")
        except subprocess.CalledProcessError:
            continue  # 그 시점에 페이지가 없던 커밋
        rec = extract(html)
        if not rec.get("ts"):
            continue  # 생성 시각이 없으면 시계열에 놓을 자리가 없다

        day_rows = rec.pop("daily", None) or []
        rec["commit"] = sha[:12]
        # 같은 생성 시각이 여러 커밋에 걸치면 마지막 커밋 것을 남긴다.
        snapshots[rec["ts"]] = rec

        # 나중 스냅샷이 같은 날짜를 다시 말하면 그쪽이 최신 실측이다.
        for row in day_rows:
            daily[row["date"]] = {"date": row["date"], "items": row["items"],
                                  "from": rec["ts"]}

    return (
        _changes_only([snapshots[k] for k in sorted(snapshots)]),
        [daily[k] for k in sorted(daily)],
    )


def write(path: Path, rows: list[dict]) -> bool:
    body = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                   for r in rows)
    if path.exists() and path.read_text(encoding="utf-8") == body:
        return False
    path.write_text(body, encoding="utf-8")
    return True


def main() -> int:
    snapshots, daily = build()
    if not snapshots:
        print("스냅샷을 하나도 만들지 못했습니다 — 추출 규칙이 페이지와 어긋났을 수 있습니다.",
              file=sys.stderr)
        return 1

    changed = [p.name for p, rows in ((SNAPSHOTS, snapshots), (DAILY, daily))
               if write(p, rows)]
    print(f"변경 스냅샷 {len(snapshots)}건 ({snapshots[0]['ts']} ~ {snapshots[-1]['ts']}) · "
          f"일별 {len(daily)}일 ({daily[0]['date']} ~ {daily[-1]['date']})"
          if daily else f"스냅샷 {len(snapshots)}건")
    print("갱신: " + (", ".join(changed) if changed else "없음"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
