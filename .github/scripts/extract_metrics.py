#!/usr/bin/env python3
"""docs/index.html 한 장에서 시계열로 쌓을 지표를 뽑는다.

페이지는 매번 덮어써지므로 값의 추세는 git history에만 남는다. 이 모듈이
그 스냅샷 하나를 기계가 읽는 레코드로 바꾼다. 찾지 못한 값은 실패가 아니라
null — 규격이 바뀌어 모듈이 사라져도 나머지 계열은 계속 쌓여야 한다.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _num(pattern: str, html: str, cast=int, group: int = 1):
    m = re.search(pattern, html, re.S)
    if not m:
        return None
    try:
        return cast(m.group(group))
    except (ValueError, IndexError):
        return None


def _bar(label: str, html: str):
    """⑤ 예제 큐의 막대 행 하나. 라벨은 ④ 실패 코드와 겹치지 않는다."""
    return _num(
        rf'<span class="bar-l">{re.escape(label)}</span>.*?<span class="bar-n">(\d+)</span>',
        html,
    )


def extract(html: str) -> dict:
    out: dict = {}

    out["ts"] = _num(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\s*생성", html, str)
    out["dday"] = _num(r'<div class="dday">D-(\d+)</div>', html)
    out["spec_rev"] = _num(r"규격 header <b>(rev\.[a-z])</b>", html, str)

    out["method"] = {
        "registered": _num(r"METHOD 인덱스 등록</span><b>(\d+)개", html),
        "candidates": _num(r"미등록 후보 · 예제 조달 대상</span><b[^>]*>(\d+)</b>", html),
        "recovery_rate": _num(r"파이프라인 회수율</span><b><b[^>]*>([\d.]+)%", html, float),
        # 회수율의 분모. 주가 넘어가면 코호트 창이 통째로 옮겨가 n이 바뀐다.
        "cohort_n": _num(r"코호트 n=(\d+)", html),
        "seed_rate": _num(r"시딩 실행률 · 예제 해결률</span><b><b>([\d.]+)%", html, float),
        "solve1_rate": _num(r"1차 <b>([\d.]+)%", html, float),
    }

    out["queue"] = {
        "backlog": _num(r'⑤</span>예제 큐<span class="sum">적체 (\d+)/\d+', html),
        "base": _num(r'⑤</span>예제 큐<span class="sum">적체 \d+/(\d+)', html),
        "wait1": _bar("1차 대기", html),
        "wait2": _bar("2차", html),
        "closed": _bar("종결", html),
        "outside": _num(r"큐 밖 \(미등록·예제없음\)</span><b>(\d+)</b>", html),
        "expired": _num(r"1차 7일 초과 \(큐 만료 대상\)</span><b>(\d+)</b>", html),
    }

    # 처리됨(해결) 항목을 로그에 기록
    out["log"] = {
        "processed": _bar("해결", html),
    }

    out["throughput"] = {
        "week_items": _num(r"이번 주 Σ 완료문항[^<]*</span><b>(\d+)</b>", html),
        "record_days": _num(r"기록일 (\d+)일 / \d+일", html),
        "window_days": _num(r"기록일 \d+일 / (\d+)일", html),
    }

    out["skills"] = {
        "unjudged": _num(r"미판정 \(숙련도 공란\)</span><b>(\d+)/\d+</b>", html),
        "total": _num(r"미판정 \(숙련도 공란\)</span><b>\d+/(\d+)</b>", html),
        "lv2plus": _num(r"숙련도 2 이상 · 게이트 통과</span><b>(\d+) · \d+</b>", html),
        "gate_passed": _num(r"숙련도 2 이상 · 게이트 통과</span><b>\d+ · (\d+)</b>", html),
        "decayed": _num(r"감쇠 \(숙련도≥2[^<]*\)</span><b>(\d+)</b>", html),
    }

    out["mock"] = {
        "done": _num(r"이번 주 실모[^<]*</span><b[^>]*>(\d+) / \d+</b>", html),
        "cap": _num(r"이번 주 실모[^<]*</span><b[^>]*>\d+ / (\d+)</b>", html),
    }

    out["errorlog"] = {
        "uncoded": _num(r'④</span>약점 \(실패 코드 분포\)<span class="sum">미코딩 (\d+)', html),
        "exception": _num(r'④</span>약점 \(실패 코드 분포\)<span class="sum">미코딩 \d+ · 예외 (\d+)', html),
        # 날짜가 비어 창 집계에서 빠지는 행 — 지표가 아니라 결함 수치다.
        "undated": _num(r"날짜 공란 (\d+)행", html),
    }

    # 「계산불가」가 늘었다는 것은 잴 수 없는 자리가 새로 생겼다는 뜻이다(야간 검토 항목).
    out["uncomputable"] = html.count("계산불가")

    scores: dict = {}
    for card in re.findall(r'<div class="card sc">(.*?)</svg>', html, re.S):
        name = _num(r'<span class="sc-n">([^<]+)</span>', card, str)
        if not name:
            continue
        scores[name.strip()] = {
            "grade": _num(r'<span class="badge grade">(\d+)등급</span>', card),
            "raw": _num(r'<span class="big">(\d+)</span>', card),
        }
    out["scores"] = scores or None

    # ⑥ 히트맵은 하루치 완료문항을 20일 창으로 들고 있다. 스냅샷을 겹쳐 모으면
    # 창 밖으로 밀려난 날까지 온전한 일별 계열이 된다.
    out["daily"] = [
        {"date": d, "items": int(n)}
        for d, n in re.findall(r'title="(\d{4}-\d{2}-\d{2}) · 완료문항 (\d+)"', html)
    ] or None

    return out


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/index.html")
    print(json.dumps(extract(path.read_text(encoding="utf-8")),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
