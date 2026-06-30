/* 탭 간 '에이전트 변경' 신호(스펙 080). Agents 뷰가 활성화·편집·생성·삭제 등 변경 직후
   notifyAgentsChanged()를 부르면, 다른 탭/창의 소비 표면(Playground 등)이 onAgentsChanged로
   받아 목록을 재페치해 stale '미반영 초안' 배지(스펙 078)를 닫는다.

   왜 BroadcastChannel인가: 같은 탭 안의 뷰 전환은 AdminShell이 활성 뷰만 마운트해 remount→재페치로
   이미 정합되지만, 별도 탭/창은 JS 컨텍스트가 분리돼 in-app 이벤트/공유 store가 건너가지 않는다.
   BroadcastChannel은 동일 출처의 다른 컨텍스트로 메시지를 전달하므로 그 경계를 넘는다(포스트한
   바로 그 컨텍스트에는 안 옴 — 송신=Agents, 수신=Playground라 무방). 미지원 환경은 no-op이고
   소비 측 포커스/가시성 백스톱(스펙 080)이 커버한다. */
const ch: BroadcastChannel | null =
  typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('agents') : null

export function notifyAgentsChanged(): void {
  ch?.postMessage('changed')
}

/** 변경 신호 구독. 해지 함수를 돌려준다(미지원 환경은 no-op). */
export function onAgentsChanged(fn: () => void): () => void {
  if (!ch) return () => {}
  const handler = () => fn()
  ch.addEventListener('message', handler)
  return () => ch.removeEventListener('message', handler)
}
