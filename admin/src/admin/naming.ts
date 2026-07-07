/* 리소스 네이밍 규칙 (스펙 148·217) — 프론트는 힌트/즉시 검사, 진실원은 서버(400).
   식별 이름(name)=규칙 적용·참조 키. 표시 = name 단독(스펙 210), 설명은 툴팁.
   스펙 217(사용자 지시): 허용=영소문자·숫자·대시(-)만. 한글·마침표 금지. */

export const NAME_RULE = /^[a-z0-9\-]+$/

export const NAME_HINT = '영소문자·숫자·대시(-)만 (한글·마침표·공백·밑줄·대문자 금지)'

/** 위반이면 사용자용 오류 메시지, 통과면 null — 서버 validate_resource_name과 동형. */
export function validateName(name: string): string | null {
  if (!name || !name.trim()) return '이름을 입력하세요.'
  if (!NAME_RULE.test(name)) return `이름 규칙 위반: ${NAME_HINT}`
  return null
}

/** 표시 이름 — 식별 이름 단독(스펙 210). */
export const displayName = (x: { name: string }): string => x.name
