#!/usr/bin/env python3
"""결함 수치가 선을 넘었는지 본다 — 아침 판단 세션 입력용.

지표가 나쁜 것과 결함은 다르다. 회수율 5.4%는 나쁜 값이지만 이미 STATE §5에
서 있는 미결이고, 매일 다시 알리면 소음이 된다. 여기서 잡는 것은 둘뿐이다.

1. OS가 스스로 선을 그어 둔 것 — 적체가 그 주 기준을 넘음 · 큐 만료 행 발생 ·
   감쇠 발생. 값이 선을 넘는 순간이 곧 조치 시점이다.
2. 지난 갱신 이후 나빠진 것 — 미코딩·날짜 공란·계산불가가 늘거나 회수율이
   떨어졌다. 「어제보다 나빠짐」은 그 자체로 판단할 거리다.

기준선은 docs/history.ndjson에서 날짜가 오늘보다 이른 마지막 스냅샷이다(#4가 쌓는 그 파일).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_metrics import extract  # noqa: E402

HISTORY = Path("docs/history.ndjson")


def _get(metrics: dict, *path):
    cur = metrics
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


# ── OS가 그어 둔 선 ────────────────────────────────────────────────
def gate_backlog(now, _base):
    a, b = _get(now, "queue", "backlog"), _get(now, "queue", "base")
    if a is None or b is None or a <= b:
        return None
    return (f"예제 적체가 그 주 기준을 넘었습니다 — {a}행 / 기준 {b}행.",
            "배정 cap을 올리거나 이월분을 줄이는 판단이 필요합니다.")


def gate_expired(now, _base):
    n = _get(now, "queue", "expired")
    if not n:
        return None
    return (f"예제 1차가 7일을 넘긴 행이 {n}건입니다 (큐 만료 대상).",
            "만료 행을 오늘 배정에 넣을지, 종결로 내릴지 정해야 합니다.")


def gate_decay(now, _base):
    n = _get(now, "skills", "decayed")
    if not n:
        return None
    return (f"감쇠 항목이 {n}건 생겼습니다 (숙련도 2 이상 · 최종접촉 21일 초과).",
            "감쇠 목록을 뽑아 Anki 카드 대상인지 판정해야 합니다.")


# ── 지난 갱신 이후 나빠진 것 ────────────────────────────────────────
def _worse(now, base, path, label, unit="", higher_is_worse=True):
    a, b = _get(base, *path), _get(now, *path)
    if a is None or b is None or a == b:
        return None
    worse = b > a if higher_is_worse else b < a
    if not worse:
        return None
    return f"{label} {a}{unit} → {b}{unit}"


def drift_uncoded(now, base):
    line = _worse(now, base, ("errorlog", "uncoded"), "미코딩 행이 늘었습니다:")
    return (line, "실패 코드가 빈 행은 지표 분모에서 빠집니다 — 전사 때 코드를 채워야 합니다.") if line else None


def drift_undated(now, base):
    line = _worse(now, base, ("errorlog", "undated"), "날짜 공란 행이 늘었습니다:")
    return (line, "날짜가 빈 행은 14일·7일 창 집계에서 통째로 빠집니다.") if line else None


def drift_uncomputable(now, base):
    a, b = base.get("uncomputable"), now.get("uncomputable")
    if a is None or b is None or b <= a:
        return None
    return (f"「계산불가」 자리가 {a}곳 → {b}곳으로 늘었습니다.",
            "새로 못 재게 된 값이 있습니다 — 측정원이 끊긴 자리를 찾아야 합니다.")


def drift_recovery(now, base):
    line = _worse(now, base, ("method", "recovery_rate"), "파이프라인 회수율이 떨어졌습니다:",
                  unit="%", higher_is_worse=False)
    return (line, "예제가 큐에서 빠져나오지 못하고 있습니다.") if line else None


RULES = [
    ("적체 초과", gate_backlog),
    ("큐 만료", gate_expired),
    ("감쇠 발생", gate_decay),
    ("미코딩 증가", drift_uncoded),
    ("날짜 공란 증가", drift_undated),
    ("계산불가 증가", drift_uncomputable),
    ("회수율 하락", drift_recovery),
]


def baseline(now_ts: str | None, path: Path = HISTORY) -> dict | None:
    """어제 마지막 스냅샷.

    직전 스냅샷을 쓰면 안 된다 — 하루에도 열댓 번 갱신되므로 같은 날 안에서는
    늘 「변화 없음」이 되어 하루 단위 악화를 통째로 놓친다. 날짜가 오늘보다
    이른 마지막 스냅샷을 기준으로 잡으면 「어제보다 나빠졌는가」가 되고,
    같은 악화를 이튿날 다시 알리지도 않는다.
    """
    if not path.exists() or not now_ts:
        return None
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l]
    today = now_ts[:10]
    earlier = [r for r in rows if (r.get("ts") or "")[:10] < today]
    return earlier[-1] if earlier else None


def run(page: Path, history: Path) -> tuple[list[tuple[str, str, str]], dict]:
    now = extract(page.read_text(encoding="utf-8"))
    base = baseline(now.get("ts"), history)
    found = []
    for name, rule in RULES:
        hit = rule(now, base) if base is not None else (
            rule(now, {}) if rule.__name__.startswith("gate_") else None)
        if hit:
            found.append((name, hit[0], hit[1]))
    return found, now


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("page", nargs="?", default="docs/index.html", type=Path)
    ap.add_argument("--history", default=HISTORY, type=Path)
    args = ap.parse_args()

    found, now = run(args.page, args.history)
    stamp = f"기준 {now.get('ts')} · D-{now.get('dday')}"
    if not found:
        print(f"결함 임계 이상 없음 ({stamp})")
        return 0

    print(f"결함 {len(found)}건 ({stamp})\n")
    for name, what, todo in found:
        print(f"### {name}\n{what}\n{todo}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
