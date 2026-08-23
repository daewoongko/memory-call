/**
 * 다소니 대표 캐릭터. 모든 역할에서 같은 원본을 사용해 브랜드가 달라 보이지
 * 않게 한다. 원본은 투명 PNG라 어떤 화면색에서도 검은 사각형이 생기지 않는다.
 */
export default function BrandMark({ size = 132 }) {
  return (
    <img
      className="brandmark dasoni-mascot"
      src="/brand/dasoni-mascot.png"
      alt=""
      width={size}
      height={size}
    />
  );
}
