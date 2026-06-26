import { ConfigProvider } from 'antd'
import './theme.css'
import AdminShell from './admin/AdminShell'
import AuthGate from './admin/AuthGate'

export default function App() {
  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#1677ff' } }}>
      <AuthGate>{(me, onLogout) => <AdminShell user={me} onLogout={onLogout} />}</AuthGate>
    </ConfigProvider>
  )
}
