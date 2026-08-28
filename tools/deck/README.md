# 발표 덱 빌드

원본 `.pptx`(PptxGenJS 산출물)를 JSON 도형 명세로 뜯어 고친 뒤 다시 조립합니다.
손대지 않은 슬라이드는 왕복해도 도형·텍스트가 한 글자도 바뀌지 않습니다.

```bash
python3 extract.py <원본_압축해제_디렉터리> original.json   # 원본 → 명세
python3 author.py                                          # 명세 → deck.json (구조 변경)
node generate.js deck.json gen.pptx <media_dir> <assets_dir>
python3 splice.py <원본_디렉터리> <gen_디렉터리> 5:5,21:24 dasoni.pptx 29
```

`splice.py` 는 차트(5번)와 표(24번)를 원본 XML 그대로 옮깁니다. `extract.py` 가
DrawingML 차트·표를 모델링하지 않기 때문이고, 두 슬라이드는 원본에서 바뀐 것이
없으므로 다시 그리지 않는 편이 안전합니다.

## 검증

LibreOffice 가 이 환경에서 파일을 못 열어 `soffice` 경로를 쓸 수 없습니다.
대신 `preview.py` 가 같은 JSON 을 pptx 좌표 그대로 HTML 로 그리고,
`shoot.mjs` 가 Chromium 으로 슬라이드별 캡처를 뜹니다. **검사하는 것과
나가는 것이 같은 명세에서 나옵니다.**

```bash
python3 preview.py && node shoot.mjs        # shots/s01.png ...
python3 <skills>/pptx/scripts/office/validate.py dasoni.pptx --original 원본.pptx
```
