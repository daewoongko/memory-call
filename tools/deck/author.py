"""Build the restructured deck spec from the extracted original.

Slides that are not touched pass through byte-identical; every new or rewritten
slide is composed from the same design tokens the original deck uses.
"""
import copy
import json
from pathlib import Path

HERE = Path(__file__).parent
original = json.loads((HERE / "original.json").read_text(encoding="utf-8"))

# ---------------------------------------------------------------- design tokens
INK, MUTED, SOFT = "231F1A", "8F857A", "554C45"
ACCENT, ACCENT_LT, TINT = "EE7A2C", "FEAD5E", "FDEEDC"
BROWN, BROWN_LT = "5C3A14", "7A4A19"
CARD, LINE, SHADOW_C = "FFFFFF", "F0E7DC", "C9B7A4"

L, R = 0.55, 9.45           # content margins
BODY_TOP = 1.52


def card(x, y, w, h, fill=CARD):
    return {"x": x, "y": y, "w": w, "h": h, "geom": "roundRect", "fill": fill,
            "radius": 0.08, "line": {"width": 1.0, "color": LINE},
            "shadow": {"blur": 10.0, "offset": 0.04, "angle": 90.0,
                       "color": SHADOW_C, "opacity": 0.22}}


def text(x, y, w, h, lines, size=11.5, color=SOFT, bold=False,
         align=None, spacing=None, anchor="t"):
    """lines: str, or list of str, or list of (text, overrides) tuples."""
    if isinstance(lines, str):
        lines = [lines]
    paragraphs = []
    for line in lines:
        over = {}
        if isinstance(line, tuple):
            line, over = line
        paragraphs.append({
            "runs": [{"text": line,
                      "size": over.get("size", size),
                      "bold": over.get("bold", bold),
                      "italic": over.get("italic", False),
                      "color": over.get("color", color),
                      "charSpacing": None}],
            "align": over.get("align", align),
            "lineSpacing": over.get("spacing", spacing),
            "lineSpacingPct": None,
        })
    return {"x": x, "y": y, "w": w, "h": h, "geom": "rect",
            "text": paragraphs, "anchor": anchor}


def head(title, subtitle):
    return [
        {"x": L, "y": 0.44, "w": 0.13, "h": 0.13, "geom": "ellipse", "fill": ACCENT_LT},
        text(0.79, 0.30, 8.6, 0.42, title, size=26, color=INK, bold=True),
        text(0.79, 0.76, 8.6, 0.30, subtitle, size=12.5, color=MUTED),
    ]


def rows(x, y, w, items, gap=0.46, label_w=1.65, size=11.5):
    """Label / value rows sharing a baseline grid."""
    out = []
    for i, (label, value) in enumerate(items):
        yy = y + i * gap
        out.append(text(x, yy, label_w, 0.26, label, size=size, color=ACCENT, bold=True))
        out.append(text(x + label_w, yy, w - label_w, gap - 0.06, value,
                        size=size, color=SOFT, spacing=size * 1.42))
    return out


def slide(title, subtitle, shapes, notes=""):
    return {"shapes": head(title, subtitle) + shapes, "notes": notes,
            "media": None, "bg": "FCFAF6"}


new = []


def keep(index):
    """Pass an original slide through untouched (1-based)."""
    new.append(copy.deepcopy(original[index - 1]))


# ============================================================ 1-6  문제 제기
for i in (1, 2, 3, 4, 5, 6):
    keep(i)

# 7, 8 (전문가 인터뷰 / 보호자 인터뷰) — 삭제. 인용은 10번·12번 안에 남는다.

# ============================================================ 7-10 해결 방향
for i in (9, 10, 11, 12):
    keep(i)

# ============================================================ 11  ① 목소리 + 지연
s = copy.deepcopy(original[13 - 1])
keep_shapes = [sh for sh in s["shapes"]
               if not (sh["x"] >= 5.15 and sh.get("text"))]   # drop the quote card text
keep_shapes = [sh for sh in keep_shapes if not (sh["x"] == 5.20 and sh["geom"] == "roundRect")]
s["shapes"] = keep_shapes + [
    card(5.20, 1.55, 4.25, 2.95, TINT),
    text(5.60, 1.86, 3.45, 0.30, "어르신이 체감하는 것은 목소리만이 아닙니다",
         size=12, color=BROWN_LT, bold=True),
    text(5.60, 2.24, 3.50, 0.62, ["“여보세요? 여보세요?”"],
         size=19, color=BROWN, bold=True, spacing=27),
    text(5.60, 2.92, 3.50, 0.56,
         "목소리가 익숙해도 응답이 늦으면 어르신은 전화가 끊긴 줄 알고 다시 부르십니다.",
         size=11, color=BROWN_LT, spacing=16),
    text(5.60, 3.56, 1.70, 0.26, "말을 마친 순간부터", size=10.5, color=BROWN_LT),
    text(5.60, 3.84, 1.70, 0.26, "첫 목소리까지", size=10.5, color=BROWN_LT),
    text(7.35, 3.52, 1.75, 0.32, "개선 전    ■.■초", size=12, color=BROWN, bold=True),
    text(7.35, 3.86, 1.75, 0.32, "개선 후    ■.■초", size=12, color=ACCENT, bold=True),
    text(5.60, 4.22, 3.50, 0.24,
         "※ tools/benchmark_call_pipeline.py 측정값으로 발표 전 확정",
         size=9, color=BROWN_LT),
]
s["shapes"][3 - 1] = text(0.79, 0.76, 8.6, 0.30,
                          "낯선 기계 음성도, 늦은 응답도 어르신에게는 같은 불안입니다",
                          size=12.5, color=MUTED)
new.append(s)

# ============================================================ 12  ② 그림일기
new.append(slide(
    "② 이야기하신 장면이 그림으로 남습니다",
    "보호자들이 이미 쓰고 계시던 방법을, 통화 기록에서",
    [
        text(L, 1.24, 8.9, 0.28,
             "“사진 같은 거 보여주는 거지. 그러면 좋아해.”   — 보호자 인터뷰 중",
             size=12, color=BROWN_LT, bold=True),
        card(L, 1.66, 2.83, 1.62),
        text(0.85, 1.86, 2.30, 0.26, "1   발화에서 장면 추출", size=12, color=ACCENT, bold=True),
        text(0.85, 2.20, 2.30, 0.90,
             "어르신이 말씀하신 장면·인물·시기를 통화 기록에서 뽑습니다.",
             size=11, color=SOFT, spacing=16),
        card(3.58, 1.66, 2.83, 1.62),
        text(3.88, 1.86, 2.30, 0.26, "2   그림일기 생성", size=12, color=ACCENT, bold=True),
        text(3.88, 2.20, 2.30, 0.90,
             "그 시절 배경과 분위기로 그림을 만들고 제목·대표 발화를 붙입니다.",
             size=11, color=SOFT, spacing=16),
        card(6.62, 1.66, 2.83, 1.62, TINT),
        text(6.92, 1.86, 2.30, 0.26, "3   확인된 기억에만 승인", size=12, color=BROWN, bold=True),
        text(6.92, 2.20, 2.30, 0.90,
             "가족이 확인한 기억과 실제 발화가 모두 있어야 승인됩니다.",
             size=11, color=BROWN_LT, spacing=16),
        # 실제 산출물
        {"x": L, "y": 3.46, "w": 2.72, "h": 1.36, "geom": "rect", "image": "diary1.png"},
        {"x": 3.64, "y": 3.46, "w": 2.72, "h": 1.36, "geom": "rect", "image": "diary2.png"},
        {"x": 6.73, "y": 3.46, "w": 2.72, "h": 1.36, "geom": "rect", "image": "diary3.png"},
        text(L, 4.86, 7.9, 0.26,
             "지금까지 92장을 만들어 직접 검수했습니다. 승인되지 않은 그림은 대화에 쓰지 않습니다.",
             size=10.5, color=MUTED),
    ],
    "그림일기는 heart_artworks 테이블. candidate → approved / rejected 상태머신이고, "
    "승인 규칙은 '가족이 확인한 memory_id 와 source_utterance_id 가 모두 존재해야 승인'.",
))

# ============================================================ 13  ③ 젊어진 얼굴
keep(15)
for sh in new[-1]["shapes"]:            # 원본에서 마감 카드가 쪽번호 위로 내려와 있었다
    if sh["y"] > 4.3:
        sh["y"] = round(sh["y"] - 0.16, 4)

# ============================================================ 14  이미지 품질 (신설)
new.append(slide(
    "이 품질까지 오는 데 버린 것들",
    "더 오래 학습한 모델이 더 좋은 모델이 아니었습니다",
    [
        card(L, BODY_TOP, 4.35, 3.02),
        text(0.90, 1.76, 3.70, 0.28, "승격한 것", size=15, color=ACCENT, bold=True),
        text(0.90, 2.10, 3.70, 0.24,
             "AI Hub 71415 공식 Validation 62명 · 실제 8세 사진은 평가 직전까지 봉인",
             size=9.5, color=MUTED),
        text(2.62, 2.44, 0.95, 0.24, "기존", size=10, color=MUTED, align="r"),
        text(3.62, 2.44, 0.98, 0.24, "300스텝", size=10, color=ACCENT, bold=True, align="r"),
    ] + [
        s for i, (lbl, before, after) in enumerate([
            ("목표 나이 오차", "12.79세", "8.14세"),
            ("실제 8세 LPIPS", "0.7035", "0.6792"),
            ("실제 8세 신원", "0.3164", "0.3260"),
            ("성인 원본 신원", "0.7699", "0.7644"),
        ]) for s in (
            text(0.90, 2.74 + i * 0.33, 1.75, 0.26, lbl, size=11, color=SOFT),
            text(2.62, 2.74 + i * 0.33, 0.95, 0.26, before, size=11, color=MUTED, align="r"),
            text(3.62, 2.74 + i * 0.33, 0.98, 0.26, after, size=11, color=INK,
                 bold=True, align="r"),
        )
    ] + [
        card(5.10, BODY_TOP, 4.35, 3.02, TINT),
        text(5.45, 1.76, 3.70, 0.28, "떨어뜨린 것", size=15, color=BROWN, bold=True),
        text(5.45, 2.10, 3.70, 0.24, "네 후보 모두 운영에 연결하지 않았습니다",
             size=9.5, color=BROWN_LT),
    ] + [
        s for i, (name, why) in enumerate([
            ("성인 → 8세 직접 생성", "신원도 아동 구조도 불안정 → 경로 자체를 제거"),
            ("5,000스텝 대량 학습", "38분 학습하고 나이 오차 +1.15세 악화"),
            ("400 · 500스텝", "나이는 맞았지만 성인 신원 0.77 → 0.65, 사람이 바뀜"),
            ("튜닝 FRAN 전체 경로", "생성 나이 29~41세, 아동 구조가 사라짐"),
        ]) for s in (
            text(5.45, 2.46 + i * 0.52, 3.70, 0.24, name, size=11, color=BROWN, bold=True),
            text(5.45, 2.70 + i * 0.52, 3.70, 0.26, why, size=10, color=BROWN_LT),
        )
    ] + [
        text(L, 4.72, 8.9, 0.30,
             "승격 기준을 먼저 정했습니다 — 나이와 LPIPS가 개선되고, 실제 8세 신원이 나빠지지 않고, "
             "성인 신원 하락이 0.01 이내. 그 기준으로 떨어뜨린 것입니다.",
             size=11, color=SOFT),
    ],
    "핵심 문장: 더 오래 학습한 모델이 더 좋은 모델이 아니다. 400·500스텝은 나이를 더 정확히 "
    "만들었지만 사람을 바꾸는 방향으로 움직였다.",
))

# ============================================================ 15-16  ④ ⑤
keep(16)
keep(17)

# ============================================================ 17  등록할 때 한 번
new.append(slide(
    "등록할 때 한 번 만들어 둡니다",
    "통화 중에는 만들지 않습니다 — 응답마다 생성하면 대화가 성립하지 않습니다",
    [
        card(L, BODY_TOP, 2.83, 2.62),
        text(0.85, 1.74, 2.30, 0.26, "목소리", size=14, color=ACCENT, bold=True),
        text(0.85, 2.06, 2.35, 0.24, "ElevenLabs IVC", size=11, color=INK, bold=True),
        text(0.85, 2.32, 2.35, 0.62,
             "general·care 두 녹음이 80초를 넘으면 즉시 등록합니다.",
             size=10.5, color=SOFT, spacing=15),
        text(0.85, 3.02, 2.35, 0.24, "PVC 승격", size=11, color=INK, bold=True),
        text(0.85, 3.28, 2.35, 0.62,
             "누적 30분에 자격, 60분에 권장. 본인 확인이 필요해 시스템이 임의로 시작하지 않습니다.",
             size=10.5, color=SOFT, spacing=15),

        card(3.58, BODY_TOP, 2.83, 2.62),
        text(3.88, 1.74, 2.30, 0.26, "얼굴", size=14, color=ACCENT, bold=True),
        text(3.88, 2.02, 2.35, 0.94,
             ["YuNet  입력 품질 검사",
              "FLUX.2 Klein 4B Inpaint",
              "개인 Identity LoRA",
              "FRAN residual U-Net  구조 가이드"],
             size=10.5, color=SOFT, spacing=15),
        text(3.88, 3.02, 2.35, 0.24, "검증 세 가지", size=11, color=INK, bold=True),
        text(3.88, 3.28, 2.35, 0.62,
             "InsightFace 신원 · MiVOLO 나이 · 3DDFA-V2 구조를 각각 독립으로 봅니다.",
             size=10.5, color=SOFT, spacing=15),

        card(6.62, BODY_TOP, 2.83, 2.62),
        text(6.92, 1.74, 2.30, 0.26, "영상 · 아바타", size=14, color=ACCENT, bold=True),
        text(6.92, 2.06, 2.35, 0.24, "RIFE ONNX", size=11, color=INK, bold=True),
        text(6.92, 2.32, 2.35, 0.62,
             "승인된 연령 사진 사이를 보간해 모핑 영상을 만들어 둡니다.",
             size=10.5, color=SOFT, spacing=15),
        text(6.92, 3.02, 2.35, 0.24, "Anam cara-4", size=11, color=INK, bold=True),
        text(6.92, 3.28, 2.35, 0.62,
             "영구 키와 avatar_id 는 서버에만 두고 브라우저에는 세션 토큰만 내려보냅니다.",
             size=10.5, color=SOFT, spacing=15),

        card(L, 4.30, 8.9, 0.72, TINT),
        text(0.85, 4.46, 8.3, 0.24, "한 번에 8세로 내려가지 않습니다",
             size=11.5, color=BROWN, bold=True),
        text(0.85, 4.70, 8.3, 0.24,
             "38 → 32 → 26 → 20 → 15 → 11 → 8세. 단계마다 후보 4~6장을 만들고 "
             "가족이 고른 사진만 다음 단계의 입력이 됩니다.",
             size=10.5, color=BROWN_LT),
    ],
    "영상은 통화 중에 만들지 않는다는 것이 이 슬라이드의 핵심. 응답마다 생성하면 건당 수백 원에 "
    "1~3분이 걸려 대화가 성립하지 않는다.",
))

# ============================================================ 18  통화할 때 매 턴
STEPS = [
    ("입력", "Web Speech API", "결과가 안 나오는 기기는 ElevenLabs Scribe v2 Realtime 으로 넘깁니다"),
    ("대화", "LLM · fast 프롬프트", "겹치는 기억 4개와 6필드만. 스트리밍으로 첫 문장부터 흘려보냅니다"),
    ("검사", "safety.py", "규칙이 답변을 실제로 교체합니다. 모델 신고값은 신뢰하지 않습니다"),
    ("음성", "ElevenLabs Flash v2.5", "24kHz PCM 스트리밍. 첫 문장이 준비되는 즉시 재생합니다"),
    ("얼굴", "Anam cara-4", "실패하면 같은 음성으로 계속됩니다. 통화가 끊기지 않습니다"),
]
step_shapes = []
for i, (tag, model, desc) in enumerate(STEPS):
    x = L + i * 1.79
    step_shapes += [
        card(x, BODY_TOP, 1.62, 2.36),
        {"x": x + 0.22, "y": 1.72, "w": 0.13, "h": 0.13, "geom": "ellipse", "fill": ACCENT_LT},
        text(x + 0.22, 1.94, 1.20, 0.24, tag, size=12, color=ACCENT, bold=True),
        text(x + 0.22, 2.22, 1.24, 0.56, model, size=10.5, color=INK, bold=True, spacing=14),
        text(x + 0.22, 2.86, 1.24, 0.92, desc, size=9.5, color=SOFT, spacing=13),
    ]
    if i < len(STEPS) - 1:
        step_shapes.append(text(x + 1.62, 2.46, 0.17, 0.26, "▶", size=11,
                                color=ACCENT_LT, bold=True, align="ctr"))
new.append(slide(
    "통화 한 턴은 이렇게 돕니다",
    "사용자가 기다리는 경로와, 기다리지 않아도 되는 경로를 나눴습니다",
    step_shapes + [
        card(L, 4.16, 8.9, 0.86, TINT),
        text(0.85, 4.32, 3.10, 0.24, "응답을 보낸 뒤 백그라운드에서",
             size=11.5, color=BROWN, bold=True),
        text(0.85, 4.58, 8.30, 0.30,
             "메타데이터 재요청(문장은 바꾸지 않음) · care 관찰 후보를 원문과 대조 검증 · "
             "리포트 집계. 여기서 실패해도 어르신은 기다리지 않습니다.",
             size=10.5, color=BROWN_LT),
    ],
    "turn() 은 동기, finish_turn_metadata() 는 BackgroundTasks. 숫자는 DB 집계라 모델이 "
    "실패해도 리포트는 나온다.",
))

# ============================================================ 19  지연 / 하지 않기로 한 것
new.append(slide(
    "지연은 성능 지표가 아니라 서비스 성립 조건입니다",
    "통화의 첫 마디가 가장 느린 것이 최악입니다",
    [
        card(L, BODY_TOP, 4.35, 3.16),
        text(0.90, 1.76, 3.70, 0.28, "지연을 줄인 네 가지", size=15, color=ACCENT, bold=True),
    ] + [
        s for i, (n, title_, desc) in enumerate([
            ("1", "프롬프트를 두 벌로 나눔",
             "통화용은 이번 발화와 겹치는 기억 4개·6필드만. 전체 맥락은 리포트용에만"),
            ("2", "첫 문장이 나오는 즉시 합성",
             "스트리밍 출력을 문장 경계에서 잘라 TTS 를 먼저 시작합니다"),
            ("3", "메타데이터를 응답 뒤로",
             "분석·집계를 BackgroundTasks 로 빼서 사용자가 기다리지 않게 했습니다"),
            ("4", "모핑 24초 동안 모델 워밍업",
             "첫 연결과 스키마 준비 비용을 인트로 영상 뒤에 숨깁니다"),
        ]) for s in (
            text(0.90, 2.16 + i * 0.62, 0.24, 0.24, n, size=11, color=ACCENT_LT, bold=True),
            text(1.16, 2.16 + i * 0.62, 3.44, 0.24, title_, size=11.5, color=INK, bold=True),
            text(1.16, 2.41 + i * 0.62, 3.44, 0.36, desc, size=9.5, color=SOFT, spacing=13),
        )
    ] + [
        card(5.10, BODY_TOP, 4.35, 3.16, TINT),
        text(5.45, 1.76, 3.70, 0.28, "하지 않기로 한 것", size=15, color=BROWN, bold=True),
    ] + [
        s for i, (name, why) in enumerate([
            ("SadTalker · D-ID 실시간 립싱크", "응답당 수십 초. MuseTalk 을 발화당 4초로 붙였지만 선택 경로로만 둡니다"),
            ("통화 중 영상 생성", "건당 수백 원에 1~3분. 등록 시점에 미리 만들어 둡니다"),
            ("PostgreSQL · pgvector", "기억 30개에 벡터DB 는 과잉. 2-gram 문자 겹침으로 랭킹합니다"),
            ("관리형 SFU", "연결 실패가 장애가 아니라 'AI 가 대신 받는다'는 정상 동작입니다"),
        ]) for s in (
            text(5.45, 2.16 + i * 0.62, 3.70, 0.24, name, size=11.5, color=BROWN, bold=True),
            text(5.45, 2.41 + i * 0.62, 3.70, 0.36, why, size=9.5, color=BROWN_LT, spacing=13),
        )
    ] + [
        text(L, 4.84, 7.9, 0.28,
             "되돌리자는 제안은 하지 않기로 문서에 적어 두었습니다. 같은 논의를 두 번 하지 않기 위해서입니다.",
             size=10.5, color=MUTED),
    ],
    "지연 수치는 11번에서 이미 보여줬으므로 여기서는 방법만 말한다.",
))

# ============================================================ 20  안전 계층
new.append(slide(
    "규칙이 1차, 모델은 보조입니다",
    "더 다정한 대답이 어르신을 하루 종일 현관 앞에 세워 둘 수 있습니다",
    [
        card(L, BODY_TOP, 4.35, 2.62),
        text(0.90, 1.76, 3.70, 0.28, "두 겹으로 막습니다", size=15, color=ACCENT, bold=True),
        text(0.90, 2.18, 0.60, 0.24, "1차", size=10.5, color=ACCENT_LT, bold=True),
        text(1.48, 2.18, 3.12, 0.24, "persona_system.md", size=11, color=INK, bold=True),
        text(1.48, 2.44, 3.12, 0.42, "페르소나 규칙으로 애초에 그런 말을 하지 않게 합니다",
             size=10, color=SOFT, spacing=14),
        text(0.90, 2.94, 0.60, 0.24, "2차", size=10.5, color=ACCENT_LT, bold=True),
        text(1.48, 2.94, 3.12, 0.24, "safety.py", size=11, color=INK, bold=True),
        text(1.48, 3.20, 3.12, 0.52,
             "규칙 검사가 답변을 실제로 교체합니다. 교체된 응답은 맥락·행동 데이터를 전부 버립니다",
             size=9.5, color=SOFT, spacing=13),
        text(0.90, 3.68, 3.70, 0.40,
             "모델이 스스로 신고한 값은 신뢰하지 않습니다. 평가는 실제 문장을 검사합니다.",
             size=9.5, color=MUTED, spacing=13),

        card(5.10, BODY_TOP, 4.35, 2.62, TINT),
        text(5.45, 1.76, 3.70, 0.28, "고칠 때마다 돌리는 자동 평가",
             size=15, color=BROWN, bold=True),
        text(5.45, 2.16, 1.80, 0.34, "35", size=22, color=BROWN, bold=True),
        text(6.15, 2.26, 1.60, 0.24, "안전 시나리오", size=10.5, color=BROWN_LT),
        text(7.45, 2.16, 1.80, 0.34, "10", size=22, color=BROWN, bold=True),
        text(8.05, 2.26, 1.40, 0.24, "관찰 회귀", size=10.5, color=BROWN_LT),
        text(5.45, 2.68, 3.70, 0.24, "규칙 예", size=11, color=BROWN, bold=True),
        text(5.45, 2.92, 3.70, 1.06,
             ["등록된 일정에 없는 방문·통화 약속을 만들지 않는다",
              "verified 기억만 사실로 쓰고, partial 은 반드시 불확실하게 말한다",
              "처음 듣는 기억은 확정하지 않고 회상만 유도한다",
              "복약 판단·용량 변경·추가 복용을 권하지 않는다"],
             size=9.5, color=BROWN_LT, spacing=14),

        card(L, 4.34, 8.9, 0.72),
        text(0.90, 4.50, 8.20, 0.24, "한국어에서 부딪힌 것", size=11.5, color=ACCENT, bold=True),
        text(0.90, 4.74, 8.20, 0.24,
             "“아버지”는 “할아버지” 안에 들어 있습니다. 부분 문자열 하나 때문에 정서 독점 규칙이 "
             "통째로 무력화된 적이 있습니다.",
             size=10.5, color=SOFT),
    ],
    "일반 대화 AI 는 '응 갈게'라고 답한다. 그게 더 다정하니까. 그런데 어르신은 그 말을 사실로 "
    "기억하고 하루 종일 현관 앞에서 기다린다.",
))

# ============================================================ 21-22  시연 두 장
def demo(title, subtitle, shots, note, footer):
    shapes = []
    for i, (label, caption) in enumerate(shots):
        col, row = i % 2, i // 2
        x = L + col * 4.55
        y = BODY_TOP + row * 1.72
        shapes += [
            card(x, y, 4.35, 1.32, TINT),
            text(x + 0.30, y + 0.50, 3.75, 0.32, label, size=12, color=BROWN_LT,
                 bold=True, align="ctr"),
            text(x, y + 1.38, 4.35, 0.26, caption, size=10.5, color=SOFT, align="ctr"),
        ]
    shapes.append(text(L, 4.88, 7.9, 0.26, footer, size=10, color=MUTED))
    return slide(title, subtitle, shapes, note)


new.append(demo(
    "시연 ① — 전화를 받고, 거짓말을 하지 않습니다",
    "영상에서 보실 네 장면입니다",
    [("발신 → 24초", "가족 얼굴 카드를 누르고 기다립니다"),
     ("AI 인계 + 모핑", "가족이 받지 않으면 준비된 AI 가 대신 받습니다"),
     ("“오늘 집에 오니?”", "오늘 일정이 없으므로 오겠다고 하지 않습니다"),
     ("“강릉 기억나니?”", "등록되지 않은 기억이라 맞장구 대신 되묻습니다")],
    "2막에 시간을 제일 많이 쓴다. 일반 대화 AI 는 '응 갈게'라고 답한다.",
    "※ 캡처 자리입니다. 실제 화면 캡처를 넣으면 각 칸이 그대로 채워집니다.",
))

new.append(demo(
    "시연 ② — 가족은 무엇을 받는가",
    "통화가 끝난 뒤 보호자 화면에서 확인합니다",
    [("낙상 감지", "위험 발화에 노란 띠가 뜨고 가족에게 알립니다"),
     ("확인이 필요한 이야기", "가족이 승인해야 다음 통화부터 사실로 씁니다"),
     ("그림일기", "말씀하신 장면이 그림으로 남습니다"),
     ("분석 리포트", "반복 질문·관찰 신호·안전 규칙이 고친 횟수")],
    "AI 가 스스로 기억을 늘리지 못한다는 것이 이 장면의 핵심.",
    "※ 캡처 자리입니다. 실제 화면 캡처를 넣으면 각 칸이 그대로 채워집니다.",
))

# ============================================================ 23-  마무리
for i in (20, 21, 22, 23, 24, 25, 26):
    keep(i)

# ---------------------------------------------------------------- 페이지 번호
total = len(new)
for i, s in enumerate(new, 1):
    stamped = False
    for sh in s["shapes"]:
        runs = [r for p in sh.get("text", []) for r in p["runs"]]
        if len(runs) == 1 and "/" in runs[0]["text"] and sh["y"] > 5.0:
            runs[0]["text"] = f"{i} / {total}"
            stamped = True
    if not stamped and s.get("media") is None:
        s["shapes"].append(text(8.9, 5.14, 0.75, 0.28, f"{i} / {total}",
                                size=9, color=MUTED, align="r"))
    else:
        for j, sh in enumerate(s["shapes"]):
            runs = [r for para in sh.get("text", []) for r in para["runs"]]
            if len(runs) == 1 and runs[0]["text"] == f"{i} / {total}":
                s["shapes"].append(s["shapes"].pop(j))
                break

(HERE / "deck.json").write_text(json.dumps(new, ensure_ascii=False, indent=1),
                                encoding="utf-8")
print(f"authored {total} slides -> deck.json")
