/* my-agents 어드민 셸 — navy 사이더 + 헤더 + 상태 기반 뷰 라우터.
   handoff 번들 ui_kits/admin/AdminShell.jsx를 진짜 antd 6 Layout/Menu/Sider로 재현.
   antd dark Sider 기본 배경(#001529)이 번들 navy와 동일하다. 라우터는 쓰지 않고
   내부 상태로 전환(딥링크 필요해지면 추후 react-router). */
import { useEffect, useState, type ReactNode } from 'react'
import { Layout, Menu, Avatar, Badge, Button, Dropdown, theme, Grid, message, Drawer } from 'antd'
import {
  DashboardOutlined,
  RobotOutlined,
  AppstoreOutlined,
  PartitionOutlined,
  CommentOutlined,
  CheckCircleOutlined,
  ThunderboltOutlined,
  ApiOutlined,
  FolderOpenOutlined,
  ReadOutlined,
  TeamOutlined,
  ScheduleOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  QuestionCircleOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from '@ant-design/icons'
import OverviewView from './views/OverviewView'
import AgentsView from './views/AgentsView'
import BlocksView from './views/BlocksView'
import NodeLibraryView from './views/NodeLibraryView'
import ProviderModelView from './views/ProviderModelView'
import CollectionsView from './views/CollectionsView'
import SessionsView from './views/SessionsView'
import MemoryView from './views/MemoryView'
import ApprovalsView from './views/ApprovalsView'
import UsersView from './views/UsersView'
import BatchView from './views/BatchView'
import EvalView from './views/EvalView'
import AllowedHostsView from './views/AllowedHostsView'
import SettingsView from './views/SettingsView'
import { Playground } from '../playground/Playground'
import { logout as apiLogout, listApprovals, type Me } from '../api'

const { Sider, Header, Content } = Layout

type ViewKey =
  | 'overview'
  | 'agents'
  | 'blocks'
  | 'node-library'
  | 'models'
  | 'collections'
  | 'sessions'
  | 'memory'
  | 'approvals'
  | 'users'
  | 'batch'
  | 'allowed-hosts'
  | 'settings'
  | 'eval'
  | 'debug'

const TITLES: Record<ViewKey, string> = {
  overview: '개요',
  agents: '에이전트',
  blocks: '빌딩 블록',
  'node-library': '노드',
  models: '프로바이더·모델',
  collections: 'RAG 컬렉션',
  sessions: '세션',
  memory: '메모리',
  approvals: '승인',
  users: '유저',
  batch: '배치',
  'allowed-hosts': '허용 호스트',
  settings: '설정',
  eval: '평가',
  debug: 'Playground',
}

export default function AdminShell({ user, onLogout }: { user: Me; onLogout: () => void }) {
  const [view, setView] = useState<ViewKey>('agents')
  // 에이전트 "테스트" → 플레이그라운드로 이동+그 에이전트 자동 선택(스펙 144 #2).
  const [playgroundAgent, setPlaygroundAgent] = useState<string | null>(null)
  // 컬렉션 "평가하기" → 평가로 이동+새 문제집 창 프리필(스펙 197, playground 패턴 재사용).
  const [evalCollection, setEvalCollection] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState(false)
  const { token } = theme.useToken()
  // 모바일(<768px)에서는 Sider를 오버레이로 띄우고 기본은 닫는다 — 232px 사이더가
  // 콘텐츠를 짜부라뜨리던 문제 해결. 브레이크포인트 교차 시 자동 토글.
  // useBreakpoint()는 첫 페인트에 {}(전부 undefined)를 반환하므로, 마운트 전에는
  // 데스크톱으로 간주해 데스크톱 첫 로드의 백드롭 플래시를 막는다.
  const screens = Grid.useBreakpoint()
  const [mounted, setMounted] = useState(false)
  useEffect(() => {
    setMounted(true)
  }, [])
  const isMobile = mounted && !screens.md
  useEffect(() => {
    setCollapsed(isMobile)
  }, [isMobile])

  // 승인 배지는 실제 pending 수(045 정직화) — mock 상수 제거. 마운트 1회만 fetch해
  // 첫 배지값을 채운다. 승인 뷰에 들어가면 ApprovalsView가 onPendingChange로 카운트를
  // 단일 소스로 갱신(초기 로드+resolve)하므로, 여기서 [view]로 재fetch하면 두 fetch가
  // 경합해 한쪽 실패 시 배지≠목록이 재발한다 → 마운트 의존성으로 고정(적대 리뷰 045).
  const [pendingCount, setPendingCount] = useState(0)
  useEffect(() => {
    let alive = true
    listApprovals('pending')
      .then((items) => {
        if (alive) setPendingCount(items.length)
      })
      .catch(() => {
        /* 배지 카운트 실패는 조용히 무시(목록 화면에서 별도 에러 표기) */
      })
    return () => {
      alive = false
    }
  }, [])

  const menuItems = [
    { key: 'overview', icon: <DashboardOutlined />, label: '개요' },
    { key: 'agents', icon: <RobotOutlined />, label: '에이전트' },
    { key: 'blocks', icon: <AppstoreOutlined />, label: '빌딩 블록' },
    // 노드 라이브러리(스펙 316) — 노드형 파이프라인의 재사용 노드 카탈로그(공유, admin 전용 아님).
    { key: 'node-library', icon: <PartitionOutlined />, label: '노드' },
    { key: 'collections', icon: <FolderOpenOutlined />, label: 'RAG 컬렉션' },
    { key: 'sessions', icon: <CommentOutlined />, label: '세션' },
    { key: 'memory', icon: <ReadOutlined />, label: '메모리' },
    {
      key: 'approvals',
      icon: <CheckCircleOutlined />,
      label: (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          승인
          {pendingCount > 0 && (
            <Badge count={pendingCount} color={token.colorPrimary} size="small" />
          )}
        </span>
      ),
    },
    // 프로바이더·모델·유저·배치·허용 호스트·설정은 admin 보호 라우트 — 슈퍼유저에게만 노출하고
    // "관리자" 그룹 헤더로 일반 작업 메뉴와 시각 구분(spec 065; "도구" 그룹과 동일 패턴).
    // 노출 게이트는 UX 편의일 뿐, 서버 라우터가 require(...,"manage")로 독립 강제(064 §D5, 174).
    // 프로바이더·모델은 변이만 _manage — GET /models는 _auth라 에이전트/RAG 폼 모델 선택은 무영향.
    ...(user.is_superuser
      ? [
          {
            type: 'group' as const,
            label: collapsed ? '' : '관리자',
            children: [
              { key: 'models', icon: <ApiOutlined />, label: '프로바이더·모델' },
              { key: 'users', icon: <TeamOutlined />, label: '유저' },
              { key: 'batch', icon: <ScheduleOutlined />, label: '배치' },
              { key: 'allowed-hosts', icon: <SafetyCertificateOutlined />, label: '허용 호스트' },
              { key: 'settings', icon: <SettingOutlined />, label: '설정' },
            ],
          },
        ]
      : []),
    {
      type: 'group' as const,
      label: collapsed ? '' : '도구',
      children: [
        { key: 'debug', icon: <ThunderboltOutlined />, label: 'Playground' },
        { key: 'eval', icon: <CheckCircleOutlined />, label: '평가' },
        // 가이드 — 뷰 전환이 아니라 정적 HTML(public/guide, docs/guide/build-html.py 산출)을
        // 새 탭으로 연다. onSelect에서 가로채므로 ViewKey에 포함하지 않는다.
        { key: 'guide', icon: <QuestionCircleOutlined />, label: '가이드' },
      ],
    },
  ]

  const views: Record<ViewKey, ReactNode> = {
    overview: <OverviewView onGo={(v) => setView(v as ViewKey)} />,
    agents: (
      <AgentsView
        meId={user.id}
        onOpenPlayground={(id) => {
          setPlaygroundAgent(id)
          setView('debug')
        }}
      />
    ),
    blocks: <BlocksView />,
    'node-library': <NodeLibraryView />,
    models: <ProviderModelView />,
    collections: <CollectionsView onEvaluate={(cid) => { setEvalCollection(cid); setView('eval') }} />,
    sessions: <SessionsView />,
    memory: <MemoryView />,
    approvals: <ApprovalsView onPendingChange={setPendingCount} />,
    users: <UsersView />,
    batch: <BatchView />,
    eval: <EvalView initialCollectionId={evalCollection} onConsumedInitial={() => setEvalCollection(null)} />,
    'allowed-hosts': <AllowedHostsView />,
    settings: <SettingsView />,
    debug: <Playground initialAgentId={playgroundAgent} onConsumedInitial={() => setPlaygroundAgent(null)} meIsSuperuser={user.is_superuser} />,
  }

  const doLogout = async () => {
    try {
      await apiLogout()
    } catch {
      message.error('로그아웃 요청 실패 — 세션을 정리합니다')
    } finally {
      onLogout()
    }
  }

  return (
    <Layout style={{ height: '100vh' }}>
      {(() => {
        /* 모바일 내비를 antd Drawer로(스펙 204) — 수제 백드롭+fixed Sider 제거, mask·애니메이션·
           바깥클릭 닫기를 antd에 이양. 데스크톱은 기존 Sider 그대로(무회귀). */
        const sider = (
          <Sider
            theme="dark"
            width={232}
            collapsedWidth={72}
            collapsed={isMobile ? false : collapsed}
            trigger={null}
            style={isMobile ? { height: '100%' } : undefined}
          >
        {/* antd는 children을 .ant-layout-sider-children(height:100%)로 감싼다.
            그 안에서 flex column 한 겹을 더 둬야 메뉴가 늘어나고 칩이 바닥에 붙는다. */}
        <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
        {/* 로고 */}
        <div
          style={{
            height: 60,
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: collapsed ? '0 22px' : '0 20px',
            flex: 'none',
          }}
        >
          <span
            style={{
              width: 28,
              height: 28,
              borderRadius: 7,
              background: token.colorPrimary,
              color: '#fff',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              flex: 'none',
            }}
          >
            <RobotOutlined style={{ fontSize: 16 }} />
          </span>
          {!collapsed && (
            <span style={{ color: '#fff', fontSize: 17, fontWeight: 600, whiteSpace: 'nowrap' }}>
              my-agents
            </span>
          )}
        </div>

        <div style={{ flex: 1, overflow: 'auto', paddingTop: 4 }}>
          <Menu
            theme="dark"
            mode="inline"
            selectedKeys={[view]}
            // onClick(onSelect 아님) — onSelect는 **이미 선택된 항목 재클릭에 발화하지 않아**,
            // 기본 뷰(agents)를 첫 클릭할 때 모바일 드로어가 안 닫히고 mask가 화면을 막았다(스펙 206
            // 검증 중 실측). onClick은 재클릭 포함 항상 발화.
            onClick={({ key }) => {
              if (key === 'guide') {
                // 가이드는 뷰가 아니라 정적 문서 — 새 탭으로 열고 현재 뷰 유지.
                window.open('/guide/index.html', '_blank', 'noopener')
                return
              }
              setView(key as ViewKey)
              if (isMobile) setCollapsed(true)
            }}
            items={menuItems}
            style={{ borderInlineEnd: 'none' }}
          />
        </div>

        {/* 로그인 사용자 + 로그아웃 */}
        <div
          style={{
            flex: 'none',
            padding: 12,
            borderTop: '1px solid rgba(255,255,255,.08)',
          }}
        >
          <Dropdown
            trigger={['click']}
            placement="topLeft"
            menu={{
              items: [
                { key: 'who', label: user.email, disabled: true },
                { type: 'divider' as const },
                { key: 'logout', icon: <LogoutOutlined />, label: '로그아웃', onClick: () => void doLogout() },
              ],
            }}
          >
            <div
              style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 8px', cursor: 'pointer', borderRadius: 6 }}
            >
              <Avatar size="small" style={{ background: 'var(--volcano-6)', flex: 'none' }}>
                {(user.display_name || user.email).charAt(0).toUpperCase()}
              </Avatar>
              {!collapsed && (
                <div style={{ color: 'rgba(255,255,255,.85)', fontSize: 13, lineHeight: 1.2, minWidth: 0 }}>
                  <div style={{ fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {user.display_name || user.email}
                  </div>
                  <div style={{ color: 'rgba(255,255,255,.45)', fontSize: 11 }}>
                    {user.is_superuser ? '슈퍼유저' : '사용자'}
                  </div>
                </div>
              )}
            </div>
          </Dropdown>
        </div>
        </div>
          </Sider>
        )
        return isMobile ? (
          <Drawer
            open={!collapsed}
            placement="left"
            size={232}
            closable={false}
            onClose={() => setCollapsed(true)}
            styles={{ body: { padding: 0 } }}
          >
            {sider}
          </Drawer>
        ) : (
          sider
        )
      })()}

      <Layout>
        <Header
          style={{
            height: 60,
            lineHeight: '60px',
            background: '#fff',
            borderBottom: '1px solid var(--color-border-secondary)',
            display: 'flex',
            alignItems: 'center',
            gap: 16,
            padding: isMobile ? '0 12px 0 0' : '0 24px 0 0',
          }}
        >
          <Button
            type="text"
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={() => setCollapsed((c) => !c)}
            style={{ width: 60, height: 60, fontSize: 18 }}
          />
          <h3 style={{ fontSize: 18, margin: 0 }}>{TITLES[view]}</h3>
          <div style={{ flex: 1 }} />
          {/* 스펙 213: 배선 안 된 전역 검색 껍데기 제거(각 목록은 자체 검색을 이미 보유). */}
        </Header>

        {/* shared.tsx Drawer는 fixed(뷰포트 기준)로 덮는다 — absolute(이 영역 기준)는 스크롤 시
            하단이 노출되던 버그(128 중 수정). position:relative는 다른 absolute 자식 대비 유지. */}
        <Content style={{ overflow: 'auto', display: 'flex', flexDirection: 'column', position: 'relative' }}>
          {views[view]}
        </Content>
      </Layout>
    </Layout>
  )
}
