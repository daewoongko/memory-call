export const CALL_STYLE_DIMENSIONS = [
  {
    id: "tone", left: "C", right: "B", short: "목소리와 분위기",
    leftName: "차분", rightName: "활기",
    description: "목소리와 표정의 에너지",
  },
  {
    id: "response", left: "E", right: "P", short: "대응 방식",
    leftName: "공감", rightName: "실용",
    description: "감정을 먼저 받는지, 상황을 먼저 정리하는지",
  },
  {
    id: "topic", left: "M", right: "O", short: "대화 화제",
    leftName: "추억", rightName: "현재",
    description: "확인된 옛 기억과 오늘의 일상 중 어디에서 시작하는지",
  },
  {
    id: "lead", left: "L", right: "G", short: "대화 주도",
    leftName: "경청", rightName: "안내",
    description: "어르신의 속도를 따르는지, 한 가지를 제안하는지",
  },
];

export const CALL_STYLE_SCENES = [
  {
    id: "scene_1",
    title: "통화가 연결된 첫 순간",
    situation: "화면이 켜지고 어르신 얼굴이 보여요. 첫마디를 건넨다면?",
    choices: [
      { id: "a", line: "{elder}, 저예요. 지난번에 하시던 그 이야기, 더 듣고 싶었어요.", phrase: "그 이야기 더 듣고 싶어요.", axes: { tone: "C", topic: "M", lead: "L" } },
      { id: "b", line: "{elder}, 저예요. 오늘은 어떻게 지내셨어요?", phrase: "오늘은 어떻게 지내셨어요?", axes: { tone: "C", topic: "O", lead: "L" } },
      { id: "c", line: "{elder}! 얼굴 보니까 너무 좋다. 오늘 뭐 하셨는지 하나씩 얘기해봐요.", phrase: "얼굴 보니까 너무 좋다.", axes: { tone: "B", topic: "O", lead: "G" } },
    ],
  },
  {
    id: "scene_2",
    title: "오늘 집에 오니?",
    situation: "어제도 물으셨어요. 오늘 방문 일정은 등록되어 있지 않습니다.",
    safety: "없는 방문 약속을 만들지 않는 답변만 보여드려요.",
    choices: [
      { id: "a", line: "저도 보고 싶었어요! 오늘은 못 가지만 지금 이렇게 보고 있잖아요. {elder}은 오늘 뭐 하셨어요?", phrase: "저도 보고 싶었어요.", axes: { tone: "B", response: "E", topic: "O", lead: "L" } },
      { id: "b", line: "저도 보고 싶었어요! 오늘은 못 가지만 얼굴 보고 있잖아요. 우리 창밖부터 같이 볼까요?", phrase: "우리 같이 볼까요?", axes: { tone: "B", response: "E", topic: "O", lead: "G" } },
      { id: "c", line: "가고 싶은 마음은 저도 같아요. 오늘 가는 날은 아니에요. 대신 지난 설에 다 같이 모였던 이야기 해드릴게요.", phrase: "가고 싶은 마음은 저도 같아요.", axes: { tone: "C", response: "P", topic: "M", lead: "G" } },
    ],
  },
  {
    id: "scene_3",
    title: "같은 질문을 세 번째 하실 때",
    situation: "“밥은 먹었니?”를 5분 사이에 세 번째 물으세요.",
    safety: "“아까 말했잖아요”라고 나무라지 않는 답변만 보여드려요.",
    choices: [
      { id: "a", line: "네, 먹었어요. {elder}이 늘 그렇게 챙겨주셨죠.", phrase: "늘 그렇게 챙겨주셨죠.", axes: { tone: "C", response: "E", topic: "M" } },
      { id: "b", line: "네, 먹었어요. {elder}은 아직이시죠? 지금 열두 시예요.", phrase: "지금 열두 시예요.", axes: { tone: "C", response: "P", topic: "O" } },
      { id: "c", line: "저 잘 먹었어요! {elder}이 해주시던 그 된장국, 그거 또 먹고 싶어요.", phrase: "그거 또 먹고 싶어요.", axes: { tone: "B", response: "P", topic: "M" } },
    ],
  },
  {
    id: "scene_4",
    title: "저녁 약 드실 시간",
    situation: "등록된 저녁 약 시간이 되었습니다.",
    safety: "등록된 시간만 안내하고 복용량을 바꾸지 않습니다.",
    choices: [
      { id: "a", line: "약 챙기는 게 번거로우시죠. 예전엔 시간 딱딱 지키셨는데. 지금은 어떠세요?", phrase: null, axes: { response: "E", topic: "M", lead: "L" } },
      { id: "b", line: "마음 쓰이시죠? 지금 일곱 시예요. 저랑 같이 하나만 해봐요.", phrase: null, axes: { response: "E", topic: "O", lead: "G" } },
      { id: "c", line: "지금 일곱 시, 저녁 약 시간이에요. 예전에 하시던 대로 물 한 잔 먼저 놓아볼까요?", phrase: null, axes: { response: "P", topic: "M", lead: "G" } },
    ],
  },
  {
    id: "scene_5",
    title: "말없이 화면만 바라보실 때",
    situation: "인사를 건넸는데 아무 말씀 없이 화면만 보고 계세요. 10초가 지났습니다.",
    choices: [
      { id: "a", line: "…{elder}, 괜찮으세요? 저 여기 있어요. 천천히 말씀하셔도 돼요.", phrase: "천천히 말씀하셔도 돼요.", axes: { tone: "C", response: "E", topic: "O", lead: "L" } },
      { id: "b", line: "{elder}! 우리 예전에 갔던 그 냇가 기억나세요? 그 얘기 좀 해주세요.", phrase: "그 얘기 좀 해주세요.", axes: { tone: "B", response: "E", topic: "M", lead: "G" } },
      { id: "c", line: "{elder}, 지금 창밖이 밝네요. 편하실 때 말씀하세요.", phrase: "편하실 때 말씀하세요.", axes: { tone: "C", response: "P", topic: "O", lead: "L" } },
    ],
  },
  {
    id: "scene_6",
    title: "머리가 좀 어지럽네",
    situation: "통화 중 어르신이 어지럽다고 말씀하십니다.",
    safety: "모든 답변은 상태를 확인하고 가족에게 알리는 절차로 이어집니다.",
    choices: [
      { id: "a", line: "어머, 어지러우세요? 어디가 어떻게 불편하신지 말씀해 주세요. 가족에게도 바로 알릴게요.", phrase: null, axes: { tone: "B", response: "P", lead: "L" } },
      { id: "b", line: "많이 놀라셨죠. 제가 옆에 있어요. 지금 앉아 계세요. 가족에게 바로 알릴게요.", phrase: null, axes: { tone: "C", response: "E", lead: "G" } },
      { id: "c", line: "{elder}, 우선 앉으세요! 제가 지금 바로 가족에게 연락할게요.", phrase: null, axes: { tone: "B", response: "P", lead: "G" } },
    ],
  },
];

export const CALL_STYLE_TYPES = {
  CEML: ["조용한 툇마루", "차분하게 마음을 먼저 받아주고, 확인된 옛이야기를 끝까지 들어주는 말투"],
  CEMG: ["옛길 등불", "마음을 차분히 다독인 뒤 좋았던 기억 쪽으로 대화를 이끄는 말투"],
  CEOL: ["고요한 창가", "조용한 톤으로 오늘의 기분을 서두르지 않고 받아주는 말투"],
  CEOG: ["저녁 등불", "마음을 먼저 안아준 뒤 오늘 할 일 하나를 자상하게 건네는 말투"],
  CPML: ["오래된 책장", "혼란을 차분히 정리하고 확인된 추억은 묵묵히 들어주는 말투"],
  CPMG: ["옛 이정표", "사실을 분명히 짚은 뒤 익숙한 기억으로 대화를 옮기는 말투"],
  CPOL: ["잔잔한 물가", "지금 상황을 차분히 알려주고 어르신의 답을 기다리는 말투"],
  CPOG: ["든든한 나침반", "차분하고 분명하게 혼란을 줄이고 다음 한 가지를 안내하는 말투"],
  BEML: ["환한 사랑방", "환하게 반기며 어르신이 꺼내는 옛이야기를 즐겁게 듣는 말투"],
  BEMG: ["신나는 옛노래", "활기를 전하며 자랑스러웠던 기억으로 기분을 북돋는 말투"],
  BEOL: ["볕 좋은 마당", "밝고 친근하게 오늘의 마음을 받아주며 곁을 지키는 말투"],
  BEOG: ["가벼운 산책", "환하게 반긴 뒤 기분이 트이는 오늘의 일 하나를 제안하는 말투"],
  BPML: ["맑은 앨범", "활기 있게 사실을 짚고 옛 기억은 편하게 들어주는 말투"],
  BPMG: ["씩씩한 징검다리", "또렷하게 상황을 정리하고 익숙한 기억을 딛고 건너가는 말투"],
  BPOL: ["시원한 아침", "환하게 맞으며 지금 사실을 알려주되 답은 기다려주는 말투"],
  BPOG: ["경쾌한 나침반", "생기 있게 혼란을 줄이고 오늘 할 일을 하나씩 안내하는 말투"],
};

export const CALL_STYLE_TOTAL_SCENES = CALL_STYLE_SCENES.length;
// 이전 화면에서 참조하던 이름은 호환을 위해 남기되 값은 새 카드 수입니다.
export const CALL_STYLE_TOTAL_QUESTIONS = CALL_STYLE_TOTAL_SCENES;

const AXIS_COPY = {
  tone: { C: "차분하게", B: "활기 있게" },
  response: { E: "공감을 먼저", P: "상황을 먼저" },
  topic: { M: "확인된 추억으로", O: "오늘 이야기로" },
  lead: { L: "기다리며", G: "한 가지씩 안내하며" },
};

const INSTRUCTION_COPY = {
  tone: {
    C: ["차분한 쪽을 기본으로 하되 어르신 반응에 맞춘다.", "대체로 낮고 차분한 속도로 말한다.", "낮고 차분한 속도로 서두르지 않고 말한다."],
    B: ["활기 있는 쪽을 기본으로 하되 어르신 반응에 맞춘다.", "대체로 활기 있는 목소리로 반긴다.", "활기 있게 반기되 큰 목소리로 재촉하지 않는다."],
  },
  response: {
    E: ["공감을 먼저 짧게 건네는 쪽을 기본으로 한다.", "대체로 감정을 먼저 받아준 뒤 사실을 확인한다.", "감정을 먼저 분명히 받아준 뒤 필요한 사실을 확인한다."],
    P: ["상황을 먼저 정리하는 쪽을 기본으로 한다.", "대체로 확인된 사실과 방법을 먼저 전한다.", "확인된 사실과 다음 방법을 짧고 분명하게 전달한다."],
  },
  topic: {
    M: ["확인된 추억에서 시작하는 쪽을 기본으로 한다.", "등록되어 확인된 가족 기억을 주로 대화 소재로 쓴다.", "등록되어 확인된 가족 기억을 우선 대화 소재로 사용한다."],
    O: ["오늘의 맥락에서 시작하는 쪽을 기본으로 한다.", "현재 시간과 주변 상황을 주로 대화 소재로 쓴다.", "현재 시간·일정·주변 상황 같은 지금의 맥락을 우선 연결한다."],
  },
  lead: {
    L: ["기다리는 쪽을 기본으로 하되 필요하면 하나만 제안한다.", "대체로 어르신의 말을 기다리고 흐름을 따라간다.", "어르신의 말을 충분히 기다리고 흐름을 따라간다."],
    G: ["한 가지를 제안하는 쪽을 기본으로 하되 반응을 기다린다.", "주제나 행동을 대체로 한 번에 하나씩 제안한다.", "주제나 행동은 한 번에 하나만 자상하게 제안한다."],
  },
};

export function cleanCallStyleAnswers(answers = {}) {
  return Object.fromEntries(CALL_STYLE_SCENES.flatMap((scene) => {
    const value = answers[scene.id];
    return scene.choices.some((choice) => choice.id === value) ? [[scene.id, value]] : [];
  }));
}

export function calculateCallStyle(answers = {}) {
  const cleaned = cleanCallStyleAnswers(answers);
  if (Object.keys(cleaned).length !== CALL_STYLE_TOTAL_SCENES) return null;

  const counts = Object.fromEntries(CALL_STYLE_DIMENSIONS.map((dimension) => [dimension.id, { left: 0, right: 0 }]));
  const frequent = [];
  CALL_STYLE_SCENES.forEach((scene) => {
    const choice = scene.choices.find((item) => item.id === cleaned[scene.id]);
    Object.entries(choice.axes).forEach(([axis, value]) => {
      const dimension = CALL_STYLE_DIMENSIONS.find((item) => item.id === axis);
      counts[axis][value === dimension.left ? "left" : "right"] += 1;
    });
    if (choice.phrase) frequent.push(choice.phrase);
  });

  const scores = {};
  const instructions = [];
  const code = CALL_STYLE_DIMENSIONS.map((dimension) => {
    const { left, right } = counts[dimension.id];
    const selected = left > right ? dimension.left : dimension.right;
    const winningCount = Math.max(left, right);
    const confidence = winningCount === 5 ? "strong" : winningCount === 4 ? "medium" : "weak";
    const confidenceLabel = confidence === "strong" ? "강함" : confidence === "medium" ? "보통" : "약함";
    scores[dimension.id] = {
      left: dimension.left,
      right: dimension.right,
      left_count: left,
      right_count: right,
      left_percent: left * 20,
      right_percent: right * 20,
      selected,
      confidence,
      confidence_label: confidenceLabel,
    };
    instructions.push(INSTRUCTION_COPY[dimension.id][selected][winningCount - 3]);
    return selected;
  }).join("");

  const [name, description] = CALL_STYLE_TYPES[code];
  const summary = CALL_STYLE_DIMENSIONS.map((dimension) => AXIS_COPY[dimension.id][scores[dimension.id].selected]);
  instructions.push("낙상·길 잃음·복약 등 안전 상황에서는 이 말투보다 안전 규칙을 우선한다.");
  return { code, name, description, scores, summary, tone: instructions.join(" "), frequent };
}

export function callStylePersonaPatch(result, answers) {
  if (!result) return null;
  return {
    call_style_code: result.code,
    call_style_name: result.name,
    call_style_scores: result.scores,
    call_style_answers: cleanCallStyleAnswers(answers),
    tone: `[말투 시작점 ${result.code} · ${result.name}] ${result.tone}`,
    frequent_phrases: result.frequent,
    forbidden_phrases: ["왜 또 물어봐?", "아까 말했잖아.", "그것도 기억 안 나?", "몇 번을 말해야 해?"],
  };
}

export const DEFAULT_CALL_STYLE_CODE = "CPOG";

export function createDefaultCallStyleAnswers() {
  return { scene_1: "b", scene_2: "b", scene_3: "b", scene_4: "c", scene_5: "c", scene_6: "c" };
}

export function getDefaultCallStyle() {
  const answers = createDefaultCallStyleAnswers();
  return { answers, result: calculateCallStyle(answers) };
}
