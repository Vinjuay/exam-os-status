#!/usr/bin/env python3
"""docs/index.html 무결성·신선도 검사.

생성 스크립트는 로컬에만 있으므로 저장소에 올라온 결과물만 보고
(1) 반쯤 깨진 페이지가 Pages로 나가는 것과
(2) 생성이 멈춘 낡은 페이지를 실측으로 착각하는 것을 잡는다.

사용:
  python3 .github/scripts/check_page.py docs/index.html
  python3 .github/scripts/check_page.py docs/index.html --max-age-hours 24
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Seoul")  # 페이지의 생성 시각은 오프셋 없는 KST 표기다.
MIN_BYTES = 5000
REQUIRED_MODULES = ["③", "④", "⑤", "⑥", "⑦", "⑧", "⑨"]
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}
TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
FOOTER_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\s*생성")
MODULE_RE = re.compile(r'<span class="no">(.)</span>')
DDAY_RE = re.compile(r'<div class="dday">D-?\d+</div>')
SECRET_PATTERNS = [
    ("Notion 토큰", re.compile(r"\b(?:ntn_|secret_)[A-Za-z0-9]{24,}")),
    ("GitHub 토큰", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("OpenAI 키", re.compile(r"\bsk-[A-Za-z0-9_-]{24,}")),
    ("Authorization 헤더", re.compile(r"[Aa]uthorization\s*[:=]\s*['\"]?(?:Bearer|Basic)\s")),
    ("Notion API URL", re.compile(r"api\.notion\.com")),
]


class TagBalance(HTMLParser):
    """닫히지 않은 태그를 찾는다. html.parser는 깨진 HTML도 그냥 넘기므로 직접 센다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, int]] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag not in VOID_TAGS:
            self.stack.append((tag, self.getpos()[0]))

    def handle_startendtag(self, tag: str, attrs) -> None:
        pass  # <br/> 형태는 균형에 영향을 주지 않는다.

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS:
            return
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                unclosed = ", ".join(f"<{t}>(line {ln})" for t, ln in self.stack[i + 1:])
                self.errors.append(
                    f"line {self.getpos()[0]}: </{tag}> 앞에서 닫히지 않은 태그 — {unclosed}"
                )
                del self.stack[i:]
                return
        self.errors.append(f"line {self.getpos()[0]}: 짝 없는 </{tag}>")

    def unclosed(self) -> list[str]:
        return [f"line {ln}: <{t}> 가 닫히지 않음" for t, ln in self.stack]


def check(path: Path, max_age_hours: float | None, now: datetime) -> list[str]:
    fails: list[str] = []

    if not path.exists():
        return [f"{path} 없음 — 생성 스크립트가 결과물을 남기지 못했습니다."]

    raw = path.read_bytes()
    if len(raw) < MIN_BYTES:
        fails.append(f"파일이 {len(raw)}바이트뿐 (최소 {MIN_BYTES}) — 생성이 중간에 끊겼을 수 있습니다.")
    try:
        html = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        return fails + [f"UTF-8 디코드 실패: {e}"]

    # 1. 구조
    for needle in ("<html", "</html>", "<body", "</body>", "<title>"):
        if needle not in html:
            fails.append(f"필수 마크업 없음: {needle}")
    parser = TagBalance()
    parser.feed(html)
    parser.close()
    fails.extend(parser.errors)
    fails.extend(parser.unclosed())

    # 2. 모듈 — 하나라도 빠지면 그 모듈의 데이터 조회가 통째로 실패한 것이다.
    found = MODULE_RE.findall(html)
    for mod in REQUIRED_MODULES:
        n = found.count(mod)
        if n == 0:
            fails.append(f"모듈 {mod} 실종")
        elif n > 1:
            fails.append(f"모듈 {mod} 가 {n}번 중복")
    if not DDAY_RE.search(html):
        fails.append("HUD D-day 블록 없음")
    if "config.spec_ref" not in html:
        fails.append("header 스탬프(config.spec_ref) 없음 — 규격 대조가 빠졌습니다.")
    if "rev." not in html:
        fails.append("규격 rev 표기 없음")

    # 3. 유출 가드 — public 저장소이므로 결과물에 자격증명이 섞이면 즉시 실패시킨다.
    for label, pattern in SECRET_PATTERNS:
        if pattern.search(html):
            fails.append(f"자격증명 의심 문자열({label})이 페이지에 있습니다 — 커밋 전 제거하세요.")

    # 4. 생성 시각
    m = FOOTER_TS_RE.search(html)
    if not m:
        fails.append("footer 생성 시각 없음")
        return fails
    generated = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=TZ)

    head = TS_RE.search(html)
    if head:
        header_ts = datetime.strptime(head.group(0), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=TZ)
        gap = abs((generated - header_ts).total_seconds())
        if gap > 300:
            fails.append(f"header/footer 생성 시각이 {gap:.0f}초 어긋남 — 부분 갱신 의심")

    age_h = (now - generated).total_seconds() / 3600
    if age_h < -0.5:
        fails.append(f"생성 시각이 미래({generated:%Y-%m-%d %H:%M}) — 시계 또는 config 이상")
    print(f"생성 {generated:%Y-%m-%dT%H:%M:%S} (KST) · 경과 {age_h:.1f}시간 · {len(raw)}바이트")
    if max_age_hours is not None and age_h > max_age_hours:
        fails.append(
            f"페이지가 {age_h:.1f}시간째 갱신되지 않았습니다 (기준 {max_age_hours}시간) — "
            "로컬 생성 스크립트가 멈췄을 가능성이 큽니다."
        )
    return fails


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="docs/index.html", type=Path)
    ap.add_argument("--max-age-hours", type=float, default=None,
                    help="지정 시 생성 시각이 이보다 오래되면 실패 (신선도 감시용)")
    ap.add_argument("--now", default=None, help="테스트용 기준 시각 (ISO, KST)")
    args = ap.parse_args()

    now = (datetime.fromisoformat(args.now).replace(tzinfo=TZ)
           if args.now else datetime.now(TZ))
    fails = check(args.path, args.max_age_hours, now)
    if fails:
        print(f"\n실패 {len(fails)}건:", file=sys.stderr)
        for f in fails:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("통과 — 구조·모듈·스탬프·유출 검사 이상 없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
