/* my-agents 어드민 셸 — navy 사이더 + 헤더 + 상태 기반 뷰 라우터.
   handoff 번들 ui_kits/admin/AdminShell.jsx를 진짜 antd 6 Layout/Menu/Sider로 재현.
   antd dark Sider 기본 배경(#001529)이 번들 navy와 동일하다. 라우터는 쓰지 않고
   내부 상태로 전환(딥링크 필요해지면 추후 react-router). */
import { useState, type ReactNode } from 'react'
import { Layout, Menu, Input, Avatar, Badge, Button, theme } from 'antd'
import {
  DashboardOutlined,
  RobotOutlined,
  AppstoreOutlined,
  CommentOutlined,
  CheckCircleOutlined,
  ThunderboltOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import { PENDING_APPROVALS } from './mockData'
import OverviewView from './views/OverviewView'
import AgentsView from './views/AgentsView'
import BlocksView from './views/BlocksView'
import SessionsView from './views/SessionsView'
import ApprovalsView from './views/ApprovalsView'
import { Playground } from '../playground/Playground'

const { Sider, Header, Content } = Layout

type ViewKey = 'overview' | 'agents' | 'blocks' | 'sessions' | 'approvals' | 'debug'

const TITLES: Record<ViewKey, string> = {
  overview: '개요',
  agents: '에이전트',
  blocks: '빌딩 블록',
  sessions: '세션',
  approvals: '승인',
  debug: 'Playground',
}

export default function AdminShell() {
  const [view, setView] = useState<ViewKey>('agents')
  const [collapsed, setCollapsed] = useState(false)
  const { token } = theme.useToken()

  const menuItems = [
    { key: 'overview', icon: <DashboardOutlined />, label: '개요' },
    { key: 'agents', icon: <RobotOutlined />, label: '에이전트' },
    { key: 'blocks', icon: <AppstoreOutlined />, label: '빌딩 블록' },
    { key: 'sessions', icon: <CommentOutlined />, label: '세션' },
    {
      key: 'approvals',
      icon: <CheckCircleOutlined />,
      label: (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          승인
          {PENDING_APPROVALS > 0 && (
            <Badge count={PENDING_APPROVALS} color={token.colorPrimary} size="small" />
          )}
        </span>
      ),
    },
    {
      type: 'group' as const,
      label: collapsed ? '' : '도구',
      children: [{ key: 'debug', icon: <ThunderboltOutlined />, label: 'Playground' }],
    },
  ]

  const views: Record<ViewKey, ReactNode> = {
    overview: <OverviewView onGo={(v) => setView(v as ViewKey)} />,
    agents: <AgentsView />,
    blocks: <BlocksView />,
    sessions: <SessionsView />,
    approvals: <ApprovalsView />,
    debug: <Playground />,
  }

  return (
    <Layout style={{ height: '100vh' }}>
      <Sider theme="dark" width={232} collapsedWidth={72} collapsed={collapsed}>
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
            onSelect={({ key }) => setView(key as ViewKey)}
            items={menuItems}
            style={{ borderInlineEnd: 'none' }}
          />
        </div>

        {/* 워크스페이스 사용자 */}
        <div
          style={{
            flex: 'none',
            padding: 12,
            borderTop: '1px solid rgba(255,255,255,.08)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 8px' }}>
            <Avatar size="small" style={{ background: 'var(--volcano-6)', flex: 'none' }}>
              U
            </Avatar>
            {!collapsed && (
              <div style={{ color: 'rgba(255,255,255,.85)', fontSize: 13, lineHeight: 1.2 }}>
                <div style={{ fontWeight: 500 }}>나</div>
                <div style={{ color: 'rgba(255,255,255,.45)', fontSize: 11 }}>개인 워크스페이스</div>
              </div>
            )}
          </div>
        </div>
        </div>
      </Sider>

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
            padding: '0 24px 0 0',
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
          <div style={{ width: 220 }}>
            <Input prefix={<SearchOutlined />} placeholder="검색" allowClear />
          </div>
        </Header>

        {/* position:relative — shared.tsx의 Drawer가 이 영역을 덮는다. */}
        <Content style={{ overflow: 'auto', display: 'flex', flexDirection: 'column', position: 'relative' }}>
          {views[view]}
        </Content>
      </Layout>
    </Layout>
  )
}
