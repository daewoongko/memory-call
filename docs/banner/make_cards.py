"""배너(body.html)에서 화면 하나씩을 떼어 낱장 카드 HTML 4개를 만든다.

화면 C 는 안쪽에 <figure> 를 또 갖고 있다. 정규식 non-greedy 로 잘라내면
첫 번째 닫는 태그에서 끊겨 카드가 통째로 깨진다. 그래서 shot 시작 태그로
쪼갠 뒤 </figcaption> 다음의 </figure> 를 경계로 삼는다.
"""
import re

src = open("body.html", encoding="utf-8").read()
style = re.search(r"<style>.*?</style>", src, re.S).group(0)
links = "\n".join(re.findall(r"<link [^>]*>", src))

parts = src.split('<figure class="shot rise">')[1:]
shots = []
for part in parts:
    end = part.index("</figcaption>") + len("</figcaption>")
    end = part.index("</figure>", end) + len("</figure>")
    shots.append('<figure class="shot rise">' + part[:end])
assert len(shots) == 4, len(shots)
for i, sh in enumerate(shots):
    assert sh.count("<figure") == sh.count("</figure>"), f"shot {i} 태그 불균형"

MARK = """<svg class="mark" viewBox="0 0 46 40" aria-hidden="true">
        <path d="M6 2 15 11H7Z" fill="currentColor"/>
        <rect x="2" y="8" width="30" height="28" rx="11" fill="currentColor"/>
        <circle class="eye" cx="12" cy="21" r="3.2"/>
        <circle class="eye" cx="23" cy="21" r="3.2"/>
        <circle cx="40" cy="32" r="4" fill="currentColor"/>
      </svg>"""

CARD_CSS = """
<style>
/* 낱장 카드 — 배너와 같은 토큰을 쓰되 화면 하나를 원래 크기로 세운다.
   1080×1350 (4:5). 슬라이드에도 SNS 카드에도 그대로 들어가는 비율. */
:root { --scale: 1; }
body { margin: 0; }
.card-page {
  width: 1080px; height: 1350px;
  display: flex; flex-direction: column;
  padding: 48px 64px 52px;
}
.card-top { display: flex; align-items: center; justify-content: space-between; flex: none; }
.card-top .lockup b { font-size: 24px; }
.card-top .lockup .mark { width: 38px; height: 38px; }
.card-top .lockup span { font-size: 12px; }
.card-top .build { font-size: 13px; padding: 9px 17px; }

.stage { flex: 1; display: flex; align-items: center; justify-content: center; min-height: 0; }

/* 배너에서 쓰던 아치 기울기와 hover 는 낱장에서 필요 없다 */
.card-page .shot { gap: 36px; }
.card-page .shot .phone {
  transform: none;
  box-shadow:
    0 1px 0 rgba(255,255,255,.18) inset,
    0 40px 70px -26px rgba(0,0,0,.75),
    0 90px 130px -60px rgba(0,0,0,.6);
}
.card-page .shot .step { font-size: 13px; letter-spacing: .18em; margin-bottom: 12px; }
.card-page .shot .name { font-size: 36px; letter-spacing: -.035em; margin-bottom: 12px; }
.card-page .shot .desc { font-size: 17px; line-height: 1.7; max-width: 30ch; display: block; }
.card-page .foot { flex: none; margin-top: 0; padding-top: 22px; font-size: 13.5px; }
.card-page .foot .meta {
  font-family: var(--mono); font-size: 14px; letter-spacing: .12em;
  color: var(--brand-lit); font-variant-numeric: tabular-nums;
}
</style>
"""

TITLES = ["역할 선택", "어르신 통화 홈", "오늘의 기록", "보호자 분석 리포트"]

for i, (shot, title) in enumerate(zip(shots, TITLES), start=1):
    open(f"card-{i:02d}.html", "w", encoding="utf-8").write(f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>다소니 — {title}</title>
{links}
{style}
{CARD_CSS}
</head>
<body>
<div class="field card-page">
  <header class="card-top">
    <div class="lockup">
      {MARK}
      <b>다소니</b>
      <span>DASONI CARE</span>
    </div>
    <div class="build"><i class="dot"></i>데모 빌드 · 2026.08</div>
  </header>
  <div class="stage">
    {shot}
  </div>
  <footer class="foot">
    <div class="rules"><span>확인되지 않은 것은 맥락으로도 말하지 않는다</span></div>
    <p class="meta">{i:02d} / 04</p>
  </footer>
</div>
</body>
</html>
""")
    print("wrote", f"card-{i:02d}.html", title)
