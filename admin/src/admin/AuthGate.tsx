/* 인증 게이트 (스펙 031) — 부팅 시 /users/me로 세션을 확인하고,
   미인증이면 로그인 화면, 인증되면 자식(AdminShell)을 현재 유저와 함께 렌더한다.
   전역 401(세션 만료)도 여기로 모여 로그인 화면으로 되돌아간다. */
import { useEffect, useState, useCallback, type ReactNode } from 'react'
import { Spin } from 'antd'
import { getMe, setUnauthorizedHandler, type Me } from '../api'
import LoginScreen from './LoginScreen'

type State = { status: 'loading' } | { status: 'authed'; me: Me } | { status: 'anon' }

export default function AuthGate({
  children,
}: {
  children: (me: Me, onLogout: () => void) => ReactNode
}) {
  const [state, setState] = useState<State>({ status: 'loading' })

  const refresh = useCallback(async () => {
    try {
      const me = await getMe()
      setState(me ? { status: 'authed', me } : { status: 'anon' })
    } catch {
      // 네트워크/서버 오류 — 미인증으로 떨어뜨려 로그인 화면을 보인다.
      setState({ status: 'anon' })
    }
  }, [])

  useEffect(() => {
    void refresh()
    // 전역 401 → 익명으로(로그인 화면). 초기 getMe는 자체 처리하므로 중복 없음.
    setUnauthorizedHandler(() => setState({ status: 'anon' }))
    return () => setUnauthorizedHandler(null)
  }, [refresh])

  if (state.status === 'loading') {
    return (
      <div style={{ height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Spin size="large" />
      </div>
    )
  }
  if (state.status === 'anon') {
    return <LoginScreen onSuccess={() => void refresh()} />
  }
  return <>{children(state.me, () => setState({ status: 'anon' }))}</>
}
