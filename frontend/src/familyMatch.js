const RELATION_ALIASES = {
  손자: ["손자", "손주"],
  손녀: ["손녀", "손주"],
  아들: ["아들", "아드님"],
  딸: ["딸", "따님"],
  며느리: ["며느리"],
  사위: ["사위"],
};

// 긴 조사부터 지운다. 부분 문자열 재시도는 하지 않는다. "할아버지"가
// "아버지"에 잘못 연결되는 것보다 한 번 더 여쭙는 편이 안전하다.
const PARTICLES = [
  "이한테", "한테", "에게", "께서는", "께서", "께", "하고", "이랑", "랑",
  "으로", "로", "이는", "는", "이가", "가", "이를", "를", "이야", "야", "이아", "아", "이",
];

function normalizeToken(token) {
  let value = String(token || "").replace(/^[^0-9A-Za-z가-힣]+|[^0-9A-Za-z가-힣]+$/g, "");
  for (const particle of PARTICLES) {
    if (value.length > particle.length && value.endsWith(particle)) {
      value = value.slice(0, -particle.length);
      break;
    }
  }
  return value;
}

function tokens(text) {
  return String(text || "")
    .split(/[\s,!?./]+/)
    .map(normalizeToken)
    .filter(Boolean);
}

function personaWords(persona) {
  const relationship = persona.relationship || persona.relationship_type || "";
  return new Set([
    persona.display_name,
    relationship,
    ...(RELATION_ALIASES[relationship] || []),
  ].filter(Boolean));
}

export function matchFamily(text, personas = []) {
  const said = tokens(text);
  if (!said.length) return { status: "none", candidates: [] };

  const candidates = (personas || []).filter((persona) => {
    if (!persona?.ready) return false;
    const words = personaWords(persona);
    return said.some((word) => words.has(word));
  });

  if (candidates.length === 1) {
    return { status: "one", persona: candidates[0], candidates };
  }
  if (candidates.length > 1) return { status: "many", candidates };
  return { status: "none", candidates: [] };
}

export function familyMatchPrompt(result) {
  if (result?.status !== "many") return "가족의 이름을 다시 말씀해 주세요.";
  const names = result.candidates.map((item) => item.display_name).filter(Boolean);
  if (names.length === 2) return `두 분이 있어요. ${names[0]}와 ${names[1]} 중 누구에게 전화할까요?`;
  return `${names.join(", ")} 중 누구에게 전화할까요?`;
}

export function readyFamilyHint(personas = []) {
  const names = personas.filter((item) => item?.ready).map((item) => item.display_name).filter(Boolean);
  return names.length ? `${names.join(", ")}처럼 말씀해 주세요.` : "통화할 가족을 먼저 등록해 주세요.";
}
