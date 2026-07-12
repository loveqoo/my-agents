/* 공용 훅 — 뷰마다 복붙되던 교차 관심사를 흡수(스펙 182 구조 리뷰).
   HoC가 아니라 훅인 이유: 공유되는 건 렌더 트리가 아니라 state+effect 로직이다. 에러 표면(토스트 vs
   지속 Alert)은 소비자가 소유하도록 위임해 계약 다양성을 보존한다(주입식 HoC는 그 다양성을 죽인다). */
import { useEffect, useState } from 'react'
import { message } from 'antd'

/* 단발 데이터 페치 + 로딩 + 에러 + stale-race 가드. 뷰마다 손으로 쓰던
   `listX().then(setState).catch(message.error)` + `alive` 가드를 한 곳에.
   - deps 변경 또는 reload() 호출 시 재조회.
   - onError 주면 소비자가 에러를 소유(지속 Alert 등), 없으면 기본 토스트(errorMsg 또는 예외 메시지). */
export function useAsyncData<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
  opts?: { onError?: (e: unknown) => void; errorMsg?: string },
): { data: T | undefined; loading: boolean; error: string | null; reload: () => void } {
  const [data, setData] = useState<T>()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)
  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(null)
    fetcher()
      .then((d) => {
        if (alive) setData(d)
      })
      .catch((e: unknown) => {
        if (!alive) return
        const msg = e instanceof Error ? e.message : String(e)
        setError(msg)
        if (opts?.onError) opts.onError(e)
        else message.error(opts?.errorMsg ?? msg)
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
    // deps는 소비자가 정한다(스프레드). nonce는 reload() 트리거.
  }, [...deps, nonce]) // eslint-disable-line react-hooks/exhaustive-deps
  return { data, loading, error, reload: () => setNonce((n) => n + 1) }
}

/* mutation(생성·수정·삭제) 호출을 성공/실패 토스트로 감싼다. 성공 여부(bool)를 돌려
   모달 닫기·폼 초기화·reload 등 후속 분기를 소비자가 결정하게 한다. 버튼 로딩 상태는
   호출자가 소유(관심사 분리) — 이 함수는 호출 데코레이션(토스트)만. */
export async function runWithToast(
  fn: () => Promise<unknown>,
  opts?: { success?: string; error?: string; errorPrefix?: string },
): Promise<boolean> {
  try {
    await fn()
    if (opts?.success) message.success(opts.success)
    return true
  } catch (e) {
    const detail = e instanceof Error ? e.message : String(e)
    // errorPrefix는 원인 detail을 붙여 '수정 실패: <detail>'처럼 문맥+상세를 함께 낸다(스펙 309).
    // error(고정 문자열)와 배타 — errorPrefix가 있으면 그걸 우선한다. 성공 경로엔 관여 안 함(catch 전용).
    message.error(opts?.errorPrefix ? `${opts.errorPrefix}: ${detail}` : (opts?.error ?? detail))
    return false
  }
}
