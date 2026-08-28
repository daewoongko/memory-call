"""Render deck.json to HTML at pptx coordinates, for visual QA."""
import base64, json, sys
from pathlib import Path

HERE = Path(__file__).parent
deck = json.loads((HERE / "deck.json").read_text(encoding="utf-8"))
ASSETS = HERE.parent / "assets"
PX = 96  # 1 inch

def esc(t):
    return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

out = ["""<meta charset="utf-8"><style>
body{background:#3a3632;margin:0;padding:20px;font-family:'Malgun Gothic','Noto Sans KR',sans-serif}
.slide{position:relative;width:960px;height:540px;background:#F0E7DC;margin:0 auto 26px;overflow:hidden}
.n{position:absolute;left:-52px;top:0;color:#fff;font:600 15px sans-serif}
.s{position:absolute;box-sizing:border-box}
.t{position:absolute;white-space:pre-wrap;word-break:keep-all;line-height:1.32}
</style>"""]

for idx, slide in enumerate(deck, 1):
    bg = slide.get("bg", "FCFAF6")
    out.append(f'<div class="slide" style="background:#{bg}"><div class="n">{idx}</div>')
    if slide.get("media"):
        out.append('<div class="s" style="left:0;top:0;width:960px;height:540px;'
                   'background:#231F1A;color:#8F857A;font:14px sans-serif;'
                   'display:flex;align-items:center;justify-content:center">[ 마스코트 영상 ]</div>')
    for sh in slide["shapes"]:
        x, y = sh["x"] * PX, sh["y"] * PX
        w, h = sh["w"] * PX, sh["h"] * PX
        if sh.get("image"):
            data = base64.b64encode((ASSETS / sh["image"]).read_bytes()).decode()
            out.append(f'<img class="s" style="left:{x}px;top:{y}px;width:{w}px;'
                       f'height:{h}px;object-fit:cover" src="data:image/png;base64,{data}">')
            continue
        if not sh.get("text"):
            style = f"left:{x}px;top:{y}px;width:{w}px;height:{h}px;"
            if sh.get("fill"):
                style += f"background:#{sh['fill']};"
            if sh["geom"] == "ellipse":
                style += "border-radius:50%;"
            elif sh.get("radius"):
                style += f"border-radius:{sh['radius'] * PX}px;"
            if sh.get("line"):
                style += f"border:1px solid #{sh['line']['color']};"
            if sh.get("shadow"):
                style += "box-shadow:0 2px 10px rgba(201,183,164,.35);"
            out.append(f'<div class="s" style="{style}"></div>')
            continue
        anchor = sh.get("anchor", "t")
        style = (f"left:{x}px;top:{y}px;width:{w}px;"
                 + (f"height:{h}px;display:flex;flex-direction:column;justify-content:"
                    + {"ctr": "center", "b": "flex-end"}.get(anchor, "flex-start") + ";"))
        parts = []
        for para in sh["text"]:
            for run in para["runs"]:
                ps = (f"font-size:{run['size'] * PX / 72}px;color:#{run['color']};"
                      f"font-weight:{'700' if run['bold'] else '400'};")
                if para.get("align") == "r":
                    ps += "text-align:right;"
                elif para.get("align") == "ctr":
                    ps += "text-align:center;"
                if para.get("lineSpacing"):
                    ps += f"line-height:{para['lineSpacing'] * PX / 72}px;"
                parts.append(f'<div style="{ps}">{esc(run["text"])}</div>')
        out.append(f'<div class="t" style="{style}">{"".join(parts)}</div>')
    out.append("</div>")

(HERE / "preview.html").write_text("\n".join(out), encoding="utf-8")
print("preview.html written:", len(deck), "slides")
