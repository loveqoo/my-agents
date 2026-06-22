import { ConfigProvider } from 'antd'
import './theme.css'
import AdminShell from './admin/AdminShell'

export default function App() {
  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#1677ff' } }}>
      <AdminShell />
    </ConfigProvider>
  )
}
