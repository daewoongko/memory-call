"""Read the original deck's slide XML into a neutral JSON shape spec.

Untouched slides round-trip through this spec unchanged, so regenerating the
deck with pptxgenjs cannot drift from the original design.
"""
import json
import re
import sys
from pathlib import Path

EMU = 914400
SRC = Path(sys.argv[1])
OUT = Path(sys.argv[2])


def attr(xml, name, default=None):
    m = re.search(rf'{name}="([^"]*)"', xml)
    return m.group(1) if m else default


def first_color(xml):
    m = re.search(r'<a:solidFill><a:srgbClr val="([0-9A-Fa-f]{6})"', xml)
    return m.group(1).upper() if m else None


def unescape(text):
    return (text.replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", '"').replace("&apos;", "'")
                .replace("&amp;", "&"))


def parse_paragraphs(body):
    paragraphs = []
    for para in re.findall(r"<a:p>.*?</a:p>", body, re.S):
        ppr = re.search(r"<a:pPr[^>]*>(.*?)</a:pPr>|<a:pPr[^>]*/>", para, re.S)
        align = attr(para.split("<a:r>")[0], "algn")
        lnspc = re.search(r'<a:lnSpc><a:spcPts val="(\d+)"/></a:lnSpc>', para)
        lnpct = re.search(r'<a:lnSpc><a:spcPct val="(\d+)"/></a:lnSpc>', para)
        runs = []
        for run in re.findall(r"<a:r>.*?</a:r>", para, re.S):
            rpr = run.split("<a:t>")[0]
            text = re.search(r"<a:t>(.*?)</a:t>", run, re.S)
            runs.append({
                "text": unescape(text.group(1)) if text else "",
                "size": int(attr(rpr, "sz", "1200")) / 100,
                "bold": attr(rpr, "b") == "1",
                "italic": attr(rpr, "i") == "1",
                "color": first_color(rpr) or "231F1A",
                "charSpacing": (int(attr(rpr, "spc")) / 100
                                if attr(rpr, "spc") else None),
            })
        if not runs:
            continue
        paragraphs.append({
            "runs": runs,
            "align": align,
            "lineSpacing": int(lnspc.group(1)) / 100 if lnspc else None,
            "lineSpacingPct": int(lnpct.group(1)) / 1000 if lnpct else None,
        })
    return paragraphs


def parse_slide(path):
    xml = path.read_text(encoding="utf-8")
    shapes = []
    for sp in re.findall(r"<p:sp>.*?</p:sp>", xml, re.S):
        off = re.search(r'<a:off x="(-?\d+)" y="(-?\d+)"/>\s*<a:ext cx="(\d+)" cy="(\d+)"', sp)
        if not off:
            continue
        x, y, w, h = (int(v) / EMU for v in off.groups())
        geom = attr(sp, "prst", "rect")
        sppr = sp.split("<p:txBody>")[0]
        body = sp.split("<p:txBody>")[1] if "<p:txBody>" in sp else ""

        shape = {"x": round(x, 4), "y": round(y, 4),
                 "w": round(w, 4), "h": round(h, 4), "geom": geom}

        if "<a:noFill/>" not in sppr.split("<a:ln")[0]:
            shape["fill"] = first_color(sppr.split("<a:ln")[0])
        adj = re.search(r'<a:gd name="adj" fmla="val (\d+)"', sppr)
        if adj:
            shape["radius"] = round(int(adj.group(1)) / 100000 * min(w, h), 4)

        line = re.search(r"<a:ln w=\"(\d+)\">(.*?)</a:ln>", sppr, re.S)
        if line:
            shape["line"] = {"width": int(line.group(1)) / 12700,
                             "color": first_color(line.group(2))}
        if "<a:outerShdw" in sppr:
            sh = re.search(r"<a:outerShdw([^>]*)>(.*?)</a:outerShdw>", sppr, re.S)
            alpha = re.search(r'<a:alpha val="(\d+)"/>', sh.group(2))
            shape["shadow"] = {
                "blur": int(attr(sh.group(1), "blurRad", "0")) / EMU * 72,
                "offset": int(attr(sh.group(1), "dist", "0")) / EMU * 72,
                "angle": int(attr(sh.group(1), "dir", "0")) / 60000,
                "color": first_color(sh.group(2)),
                "opacity": int(alpha.group(1)) / 100000 if alpha else 1,
            }
        if body:
            paragraphs = parse_paragraphs(body)
            if paragraphs:
                shape["text"] = paragraphs
                shape["anchor"] = attr(body, "anchor", "t")
    
        shapes.append(shape)

    media = None
    if "<p:pic>" in xml:
        pic = re.search(r"<p:pic>.*?</p:pic>", xml, re.S).group(0)
        off = re.search(r'<a:off x="(-?\d+)" y="(-?\d+)"/><a:ext cx="(\d+)" cy="(\d+)"', pic)
        x, y, w, h = (int(v) / EMU for v in off.groups())
        rels = (path.parent / "_rels" / (path.name + ".rels")).read_text(encoding="utf-8")
        video = re.search(r'Target="\.\./media/([^"]+\.mp4)"', rels)
        poster = re.search(r'Target="\.\./media/([^"]+\.png)"', rels)
        media = {"x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4),
                 "video": video.group(1) if video else None,
                 "poster": poster.group(1) if poster else None}
    return {"shapes": shapes, "media": media}


LAYOUT_BG = {}


def layout_bg(src, slide_no):
    rels = (src / "ppt" / "slides" / "_rels" / f"slide{slide_no}.xml.rels").read_text(encoding="utf-8")
    m = re.search(r"Target=\"[^\"]*(slideLayout\d+)\.xml\"", rels)
    if not m:
        return "FCFAF6", None
    name = m.group(1)
    if name not in LAYOUT_BG:
        xml = (src / "ppt" / "slideLayouts" / f"{name}.xml").read_text(encoding="utf-8")
        bg = re.search(r"<p:bg>.*?</p:bg>", xml, re.S)
        colors = re.findall(r'srgbClr val="([0-9A-Fa-f]{6})"', bg.group(0)) if bg else []
        LAYOUT_BG[name] = colors[0].upper() if colors else "FCFAF6"
    return LAYOUT_BG[name], name


def parse_notes(path):
    if not path.exists():
        return ""
    xml = path.read_text(encoding="utf-8")
    body = re.search(r"<p:txBody>.*?</p:txBody>", xml, re.S)
    if not body:
        return ""
    lines = []
    for para in re.findall(r"<a:p>.*?</a:p>", body.group(0), re.S):
        text = "".join(re.findall(r"<a:t>(.*?)</a:t>", para, re.S))
        lines.append(unescape(text))
    return "\n".join(lines).strip()


deck = []
count = len(list((SRC / "ppt" / "slides").glob("slide*.xml")))
for i in range(1, count + 1):
    slide = parse_slide(SRC / "ppt" / "slides" / f"slide{i}.xml")
    slide["notes"] = parse_notes(SRC / "ppt" / "notesSlides" / f"notesSlide{i}.xml")
    slide["bg"], slide["layout"] = layout_bg(SRC, i)
    slide["source"] = i
    deck.append(slide)

OUT.write_text(json.dumps(deck, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"extracted {len(deck)} slides -> {OUT}")
print("shape counts:", [len(s["shapes"]) for s in deck])
