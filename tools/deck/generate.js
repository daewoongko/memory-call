// deck.json -> out.pptx, reproducing the original PptxGenJS design system.
const fs = require("fs");
const path = require("path");
const PptxGenJS = require("pptxgenjs");

const deck = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const outFile = process.argv[3];
const mediaDir = process.argv[4];
const assetDir = process.argv[5] || "assets";

const BG = "FCFAF6";
const FONT = "Malgun Gothic";

const pres = new PptxGenJS();
pres.layout = "LAYOUT_16x9"; // 10 x 5.625in, matching the original
pres.author = "패기2 다솜";
pres.title = "다소니";

for (const slide of deck) {
  const s = pres.addSlide();
  s.background = { color: slide.bg || BG };

  if (slide.media && mediaDir) {
    const video = path.join(mediaDir, slide.media.video);
    s.addMedia({
      type: "video",
      path: video,
      x: slide.media.x, y: slide.media.y, w: slide.media.w, h: slide.media.h,
    });
  }

  for (const shape of slide.shapes) {
    const opts = { x: shape.x, y: shape.y, w: shape.w, h: shape.h };

    if (shape.fill) opts.fill = { color: shape.fill };
    if (shape.line) opts.line = { color: shape.line.color, width: shape.line.width };
    if (shape.shadow) {
      opts.shadow = {
        type: "outer",
        blur: shape.shadow.blur,
        offset: Math.max(0, shape.shadow.offset),
        angle: Math.round(shape.shadow.angle) % 360,
        color: shape.shadow.color || "C9B7A4",
        opacity: shape.shadow.opacity,
      };
    }

    if (shape.image) {
      s.addImage({
        path: path.join(assetDir, shape.image),
        x: shape.x, y: shape.y, w: shape.w, h: shape.h,
        rounding: false,
      });
      continue;
    }

    const geomName = shape.geom === "roundRect" ? "roundRect"
      : shape.geom === "ellipse" ? "ellipse" : "rect";
    if (geomName === "roundRect" && shape.radius != null) {
      opts.rectRadius = shape.radius;
    }

    if (!shape.text) {
      // Fill-only decoration: card, dot, divider.
      s.addShape(pres.ShapeType[geomName], opts);
      continue;
    }

    // Text shape. The original writes zero insets and lets the box size itself.
    const runs = [];
    shape.text.forEach((para, pi) => {
      para.runs.forEach((run, ri) => {
        const last = ri === para.runs.length - 1;
        const item = {
          text: run.text,
          options: {
            fontFace: FONT,
            fontSize: run.size,
            bold: run.bold,
            italic: run.italic,
            color: run.color,
            breakLine: last && pi < shape.text.length - 1,
          },
        };
        if (run.charSpacing != null) item.options.charSpacing = run.charSpacing;
        if (para.align) item.options.align = para.align;
        if (para.lineSpacing != null) item.options.lineSpacing = para.lineSpacing;
        else if (para.lineSpacingPct != null) {
          item.options.lineSpacingMultiple = para.lineSpacingPct;
        }
        runs.push(item);
      });
    });

    const textOpts = {
      ...opts,
      isTextBox: true,
      margin: 0,
      valign: shape.anchor === "ctr" ? "middle" : shape.anchor === "b" ? "bottom" : "top",
      wrap: true,
    };
    if (shape.fill) textOpts.fill = { color: shape.fill };
    else delete textOpts.fill;
    if (!shape.line) delete textOpts.line;

    s.addText(runs, textOpts);
  }

  if (slide.notes) s.addNotes(slide.notes);
}

pres.writeFile({ fileName: outFile }).then(() => {
  console.log("wrote", outFile, deck.length, "slides");
});
