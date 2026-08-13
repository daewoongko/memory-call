/**
 * 이 기기가 누구인가.
 *
 * 지금까지 역할은 주소 해시(#elder / #child)와 localStorage 뿐이었다. 한
 * 브라우저에서 탭 두 개를 열어 보는 데모라면 충분하지만, 서버가 "지금 벨을
 * 어느 기기로 보내야 하는가"를 알 방법이 없다. 그래서 기기마다 id 를 만들어
 * 서버에 등록한다.
 *
 * 아이디와 비밀번호를 쓰지 않는 이유는 linking.js 와 같다. 치매가 있는 분이
 * 로그인 화면을 통과할 수 없다. id 는 기기가 만들고 기기가 보관한다.
 */

const KEY_DEVICE = "dasoni.deviceId";
const KEY_GUARDIAN_PERSONA = "dasoni.guardianPersona";

function read(key) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // 사파리 비공개 모드 등. 이번 세션 동안만 동작하고 다음에 다시 만든다.
  }
}

function randomId() {
  // randomUUID 는 보안 컨텍스트에서만 있다. HTTPS 를 쓰므로 보통은 있지만,
  // 없다고 통화가 막히면 안 되니 대체 경로를 둔다.
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

/** 이 기기의 고정 id. 처음 부르는 순간 만들어 저장한다. */
export function deviceId() {
  let id = read(KEY_DEVICE);
  if (!id) {
    id = `dev_${randomId().replace(/-/g, "").slice(0, 24)}`;
    write(KEY_DEVICE, id);
  }
  return id;
}

/** 이 보호자 기기의 주인이 어느 가족인가. 벨은 이 값으로 배달된다. */
export function guardianPersonaId() {
  return read(KEY_GUARDIAN_PERSONA);
}

export function setGuardianPersonaId(personaId) {
  write(KEY_GUARDIAN_PERSONA, personaId);
}

/**
 * 화면에 보일 기기 이름.
 *
 * 폰 두 대로 시험할 때 서버에 남은 기록만 보고 어느 쪽이 어느 폰인지
 * 알 수 있어야 한다. 사용자 에이전트를 그대로 저장하지 않고 기종만 남긴다.
 */
export function deviceLabel() {
  const agent = globalThis.navigator?.userAgent ?? "";
  if (/iPhone|iPad|iPod/.test(agent)) return "아이폰";
  if (/Android/.test(agent)) return "안드로이드 폰";
  if (/Macintosh/.test(agent)) return "맥";
  if (/Windows/.test(agent)) return "윈도우 PC";
  return "기기";
}
