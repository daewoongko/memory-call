export const CALL_STYLE_DIMENSIONS = [
  {
    id: "tone", left: "C", right: "B", short: "목소리와 분위기",
    leftName: "차분함", rightName: "밝음",
    description: "통화의 첫인상과 목소리·표정의 에너지를 찾습니다.",
    questions: [
      ["tone_1", "전화를 받자마자 가장 자연스러운 첫인사는?", "온화한 미소와 차분한 목소리", "환한 웃음과 활기찬 목소리"],
      ["tone_2", "평소 통화 속도와 억양은?", "낮은 톤으로 서두르지 않는다", "조금 높은 톤으로 리듬감 있게 말한다"],
      ["tone_3", "어르신이 말없이 화면만 바라보시면?", "눈을 맞추며 조용히 기다린다", "가볍게 질문하며 분위기를 환기한다"],
      ["tone_4", "통화할 때 가장 자주 보이는 표정은?", "온화하고 안정감 있는 표정", "웃음기 많고 생기 있는 표정"],
      ["tone_5", "통화를 마칠 때의 인사는?", "조용하고 자상하게 마무리한다", "씩씩하고 활기차게 손을 흔든다"],
      ["tone_6", "어르신에게 어떤 이미지로 느껴지고 싶나요?", "든든하게 기댈 수 있는 버팀목", "기분을 좋게 해주는 밝은 비타민"],
      ["tone_7", "영상통화 화면의 전체적인 분위기는?", "다정하고 차분한 보호자", "친근하고 반가운 가족·친구"],
    ],
  },
  {
    id: "response", left: "E", right: "P", short: "대응 방식",
    leftName: "공감", rightName: "실용",
    description: "감정을 먼저 안아주는지, 상황을 먼저 정리하는지 찾습니다.",
    questions: [
      ["response_1", "어르신이 다급하게 불안을 말씀하시면 가장 먼저?", "무서웠던 마음부터 알아준다", "현재 위치와 상황부터 정리한다"],
      ["response_2", "밥을 못 먹었다거나 물건을 잃었다고 하시면?", "속상하고 억울한 마음을 먼저 듣는다", "확인할 수 있는 사실과 방법을 찾는다"],
      ["response_3", "같은 질문을 세 번째 하시면?", "처음 듣는 것처럼 다정하게 반응한다", "답의 핵심을 짧고 분명하게 정리한다"],
      ["response_4", "말을 잇지 못하고 우울해하시면?", "애정 표현과 공감으로 마음을 받는다", "지금 할 수 있는 작은 행동을 제안한다"],
      ["response_5", "가족을 알아보지 못하시면?", "서운해하지 않고 보고 싶은 마음을 다독인다", "이름과 관계를 한 번 명확히 알려드린다"],
      ["response_6", "과거의 슬픈 일을 꺼내시면?", "감정을 충분히 나누며 들어드린다", "현재의 편안한 주제로 자연스럽게 옮긴다"],
      ["response_7", "말의 맥락이 잘 이어지지 않으면?", "기분과 말의 흐름을 우선 따라간다", "이해하기 쉬운 한 문장으로 정리한다"],
    ],
  },
  {
    id: "topic", left: "M", right: "O", short: "대화 화제",
    leftName: "추억", rightName: "현재·일상",
    description: "확인된 옛 기억과 지금의 일상 중 어디에서 대화가 시작되는지 찾습니다.",
    questions: [
      ["topic_1", "기분 좋은 대화를 시작할 때 자주 꺼내는 것은?", "행복했던 가족의 옛 추억", "지금 보이는 것과 오늘의 일상"],
      ["topic_2", "불안하거나 외로워 보일 때 더 자연스러운 전환은?", "익숙하고 좋은 옛 기억을 이야기한다", "지금 할 수 있는 편안한 일로 돌린다"],
      ["topic_3", "평소 더 자주 건네는 질문은?", "그때 기억과 옛날 이야기를 묻는다", "현재 위치·식사·몸 상태를 묻는다"],
      ["topic_4", "가장 나누고 싶은 통화의 모습은?", "추억을 함께 풀어놓는 정서적 대화", "오늘 하루를 챙기는 일상 케어"],
      ["topic_5", "사랑과 고마움을 전할 때 연결하는 것은?", "과거의 고생과 가족을 위한 노고", "오늘 건강하게 계셔주는 현재"],
      ["topic_6", "영상으로 더 보여드리고 싶은 것은?", "옛 앨범과 가족의 과거 모습", "지금의 가족과 오늘 찍은 모습"],
      ["topic_7", "예전 가족 이야기가 불쑥 나오면?", "그 시절 기억을 조금 더 여쭤본다", "현재 일상으로 자연스럽게 연결한다"],
    ],
  },
  {
    id: "lead", left: "L", right: "G", short: "대화 주도",
    leftName: "경청", rightName: "안내",
    description: "어르신의 속도를 따라갈지, 한 가지 방향을 제안할지 찾습니다.",
    questions: [
      ["lead_1", "통화가 연결된 직후 대화를 풀어가는 방식은?", "먼저 여쭤보고 말씀을 기다린다", "내가 편안한 주제를 하나 꺼낸다"],
      ["lead_2", "말이 끊기거나 횡설수설하시면?", "완성할 때까지 흐름을 따라간다", "이해하기 쉽게 정돈해 드린다"],
      ["lead_3", "식사·복약·휴식을 권할 때는?", "의사를 먼저 여쭤보고 기다린다", "한 가지 행동을 분명하게 제안한다"],
      ["lead_4", "통화에서 주로 맡는 역할은?", "이야기를 받아주는 든든한 청중", "일상을 하나씩 이끄는 가이드"],
      ["lead_5", "AI 통화에서 가장 중요한 환경은?", "재촉 없이 마음껏 말할 수 있는 편안함", "다음 행동을 알 수 있는 명확한 안심감"],
      ["lead_6", "리모컨 사용을 어려워하시면?", "천천히 해보실 시간을 드린다", "누를 버튼을 하나씩 알려드린다"],
      ["lead_7", "예전 직업을 지금 해야 한다고 말씀하시면?", "그 이야기를 먼저 충분히 듣는다", "현재 상황으로 자상하게 방향을 돌린다"],
    ],
  },
];

export const CALL_STYLE_TYPES = {
  CEML: ["따뜻한 추억의 안식처", "차분하게 공감하며, 확인된 옛이야기를 부담 없이 들어주는 유형"],
  CEMG: ["다정한 추억의 길잡이", "마음을 차분히 받아주고 좋은 옛 기억으로 대화를 이끄는 유형"],
  CEOL: ["포근한 일상 쉼터", "조용한 톤으로 지금의 기분과 일상을 서두르지 않고 수용하는 유형"],
  CEOG: ["안심 케어 내비게이터", "마음을 다독인 뒤 오늘의 맥락과 편안한 행동을 자상하게 이끄는 유형"],
  CPML: ["자상한 회상 조력자", "혼란을 차분히 정리하고 확인된 추억 이야기를 묵묵히 들어주는 유형"],
  CPMG: ["정돈된 추억 안내자", "사실관계를 분명히 한 뒤 좋은 기억으로 대화를 유도하는 유형"],
  CPOL: ["차분한 일상 수호자", "현재 상황을 정돈해 알려주고 어르신의 답변을 편안하게 기다리는 유형"],
  CPOG: ["든든한 생활 가이드", "차분하고 명확하게 혼란을 줄이고 다음 행동을 하나씩 안내하는 유형"],
  BEML: ["생기발랄 추억 경청자", "환하게 반기고 어르신이 꺼내는 옛이야기를 흥미롭게 들어주는 유형"],
  BEMG: ["밝은 비타민 추억 조향사", "활력을 전하며 자랑스럽고 행복한 옛이야기로 기분을 북돋는 유형"],
  BEOL: ["햇살 같은 일상 동반자", "밝고 친근하게 외로운 마음을 받아주며 오늘의 일상을 들어주는 유형"],
  BEOG: ["활력 충전 일상 리더", "환하게 반긴 뒤 기분 전환이 되는 현재 주제와 행동을 제안하는 유형"],
  BPML: ["명쾌한 추억 이야기꾼", "밝은 목소리로 혼란을 정돈하고 옛 기억을 편안하게 듣는 유형"],
  BPMG: ["생기 넘치는 추억 큐레이터", "또박또박 사실을 짚고 익숙한 성공 기억을 기분 좋게 끌어내는 유형"],
  BPOL: ["상쾌한 현시점 케어러", "환하게 맞아주며 현재 사실을 알려주되 답변의 속도는 기다리는 유형"],
  BPOG: ["명랑한 일상 메이트", "생기 있게 혼란을 줄이고 오늘 할 일을 유쾌하게 하나씩 안내하는 유형"],
};

export const CALL_STYLE_TOTAL_QUESTIONS = CALL_STYLE_DIMENSIONS.reduce(
  (total, dimension) => total + dimension.questions.length, 0,
);

export function calculateCallStyle(answers = {}) {
  const answered = CALL_STYLE_DIMENSIONS.flatMap((dimension) => dimension.questions)
    .filter(([id]) => answers[id]).length;
  if (answered !== CALL_STYLE_TOTAL_QUESTIONS) return null;

  const scores = {};
  const code = CALL_STYLE_DIMENSIONS.map((dimension) => {
    const left = dimension.questions.filter(([id]) => answers[id] === dimension.left).length;
    const right = dimension.questions.length - left;
    const selected = left > right ? dimension.left : dimension.right;
    scores[dimension.id] = {
      left: dimension.left, right: dimension.right, left_count: left, right_count: right,
      left_percent: Math.round(left / dimension.questions.length * 100),
      right_percent: Math.round(right / dimension.questions.length * 100), selected,
    };
    return selected;
  }).join("");

  const [name, description] = CALL_STYLE_TYPES[code];
  const [tone, response, topic, lead] = code;
  const instructions = [
    tone === "C" ? "낮고 차분한 속도로 서두르지 않고 말한다." : "밝고 생기 있게 반기되 큰 목소리로 재촉하지 않는다.",
    response === "E" ? "감정을 먼저 짧게 받아준 뒤 필요한 사실을 확인한다." : "확인된 사실과 다음 방법을 짧고 분명하게 전달한다.",
    topic === "M" ? "등록되어 확인된 가족 기억을 우선 대화 소재로 사용한다." : "현재 시간·일정·주변 상황 같은 지금의 맥락을 우선 연결한다.",
    lead === "L" ? "어르신의 말을 충분히 기다리고 흐름을 따라간다." : "주제나 행동은 한 번에 하나만 자상하게 제안한다.",
    "낙상·길 잃음·복약 등 안전 상황에서는 이 성향보다 안전 규칙을 우선한다.",
  ];
  const frequent = [
    tone === "C" ? "괜찮아. 천천히 말해줘." : "목소리 들으니 정말 반가워.",
    response === "E" ? "많이 걱정됐구나." : "확인된 것부터 하나씩 같이 볼게.",
    topic === "M" ? "그때 이야기를 조금 더 들려줄래?" : "지금 보이는 것부터 같이 확인해볼까?",
    lead === "L" ? "서두르지 않아도 돼. 계속 듣고 있어." : "우선 한 가지만 같이 해볼까?",
  ];
  return { code, name, description, scores, tone: instructions.join(" "), frequent };
}

export function callStylePersonaPatch(result, answers) {
  if (!result) return null;
  return {
    call_style_code: result.code,
    call_style_name: result.name,
    call_style_scores: result.scores,
    call_style_answers: answers,
    tone: `[통화 유형 ${result.code} · ${result.name}] ${result.tone}`,
    frequent_phrases: result.frequent,
    forbidden_phrases: ["왜 또 물어봐?", "아까 말했잖아.", "그것도 기억 안 나?", "몇 번을 말해야 해?"],
  };
}

// 질문을 건너뛸 때 사용하는 보수적인 기본값입니다.
// 차분한 톤(C), 사실 중심(P), 현재 맥락(O), 한 번에 하나씩 안내(G)를 선택합니다.
export const DEFAULT_CALL_STYLE_CODE = "CPOG";

export function createDefaultCallStyleAnswers() {
  const selected = { tone: "C", response: "P", topic: "O", lead: "G" };
  return Object.fromEntries(
    CALL_STYLE_DIMENSIONS.flatMap((dimension) =>
      dimension.questions.map(([id]) => [id, selected[dimension.id]]),
    ),
  );
}

export function getDefaultCallStyle() {
  const answers = createDefaultCallStyleAnswers();
  return { answers, result: calculateCallStyle(answers) };
}
