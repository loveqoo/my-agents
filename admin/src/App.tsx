import { useEffect, useState } from 'react'
import { Select, Typography, Layout, Spin, message } from 'antd'
import { listAgents, type Agent } from './api'
import Chat from './components/Chat'

export default function App() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [selected, setSelected] = useState<string | undefined>()
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let ignore = false // StrictMode 이중 실행/레이스 가드
    listAgents()
      .then((a) => {
        if (ignore) return
        setAgents(a)
        setSelected(a[0]?.id)
      })
      .catch((e) => {
        if (!ignore) message.error(String(e))
      })
      .finally(() => {
        if (!ignore) setLoading(false)
      })
    return () => {
      ignore = true
    }
  }, [])

  const current = agents.find((a) => a.id === selected)

  return (
    <Layout style={{ minHeight: '100vh', maxWidth: 1100, margin: '0 auto', padding: 24 }}>
      <Typography.Title level={3}>에이전트 채팅</Typography.Title>
      {loading ? (
        <Spin />
      ) : (
        <>
          <Select
            style={{ width: '100%', marginBottom: 16 }}
            placeholder="에이전트 선택"
            value={selected}
            onChange={setSelected}
            options={agents.map((a) => ({ value: a.id, label: a.name }))}
            notFoundContent="등록된 에이전트가 없습니다 (API로 등록하세요)"
          />
          {current && <Chat key={current.id} agent={current} />}
        </>
      )}
    </Layout>
  )
}
