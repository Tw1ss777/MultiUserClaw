import { useState, useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Agents from './pages/Agents'
import AgentDetail from './pages/AgentDetail'
import AgentCreate from './pages/AgentCreate'
import SkillStore from './pages/SkillStore'
import Channels from './pages/Channels'
import AIModels from './pages/AIModels'
import Sessions from './pages/Sessions'
import Chat from './pages/Chat'
import CronJobs from './pages/CronJobs'
import FileManager from './pages/FileManager'
import KnowledgeBase from './pages/KnowledgeBase'
import SystemSettings from './pages/SystemSettings'
import ApiAccess from './pages/ApiAccess'
import Nodes from './pages/Nodes'
import Plugins from './pages/Plugins'
import TerminalPage from './pages/Terminal'
import { isLoggedIn, getAccessToken, ssoLogin, APP_BASE } from './lib/api'


export default function App() {
  const [ssoState, setSsoState] = useState<'idle' | 'loading'>('idle')
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const mode = params.get('mode')
    const hubToken = params.get('hub_token')
    const originalPath = window.location.pathname
    if (mode) localStorage.setItem('ui_mode', mode)
    if (hubToken) {
      const routePath = APP_BASE && originalPath.startsWith(APP_BASE)
        ? originalPath.slice(APP_BASE.length) || '/'
        : originalPath
      const redirectPath = APP_BASE + (routePath === '/' || routePath === '/agent' ? '/dashboard' : routePath)
      // 解码 hub_token 的 sub（AI Hub 用户 id），仅用于判断是否需要重新 SSO，安全校验由后端 sso 接口完成
      let hubUserId = ''
      try {
        const payload = JSON.parse(
          atob(hubToken.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')),
        )
        hubUserId = payload.sub || ''
      } catch { /* 解码失败则强制重新 SSO */ }
      const lastHubUserId = localStorage.getItem('openclaw_hub_user_id')
      if (hubUserId && lastHubUserId === hubUserId && getAccessToken()) {
        // 与本地 token 属于同一用户：跳过重复 SSO，仅从 URL 移除敏感参数
        const clean = new URL(window.location.href)
        clean.searchParams.delete('hub_token')
        window.history.replaceState(history.state, '', clean.toString())
        return
      }
      setSsoState('loading')
      localStorage.removeItem('openclaw_access_token')
      localStorage.removeItem('openclaw_refresh_token')
      ssoLogin(hubToken)
        .then(() => {
          if (hubUserId) localStorage.setItem('openclaw_hub_user_id', hubUserId)
          window.location.href = redirectPath
        })
        .catch(() => {
          setSsoState('idle')
          // SSO 失败：回退到应用自己的登录页，避免卡在加载界面
          window.location.href = `${APP_BASE}/login`
        })
    }
  }, [])
  if (ssoState === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-dark-bg text-dark-text">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-accent-blue border-t-transparent" />
          <span className="text-sm text-dark-text-secondary">SSO 登录中...</span>
        </div>
      </div>
    )
  }
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<RequireAuth><Layout /></RequireAuth>}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="agents" element={<Agents />} />
        <Route path="agents/create" element={<AgentCreate />} />
        <Route path="agents/:id" element={<AgentDetail />} />
        <Route path="chat" element={<Chat />} />
        <Route path="skills" element={<SkillStore />} />
        <Route path="channels" element={<Channels />} />
        <Route path="plugins" element={<Plugins />} />
        <Route path="models" element={<AIModels />} />
        <Route path="files" element={<FileManager />} />
        <Route path="knowledge" element={<KnowledgeBase />} />
        <Route path="terminal" element={<TerminalPage />} />
        <Route path="sessions" element={<Sessions />} />
        <Route path="cron" element={<CronJobs />} />
        <Route path="nodes" element={<Nodes />} />
        <Route path="api" element={<ApiAccess />} />
        <Route path="api-set" element={<ApiAccess />} />
        <Route path="settings" element={<SystemSettings />} />
      </Route>
    </Routes>
  )
}
function RequireAuth({ children }: { children: React.ReactNode }) {
  if (!isLoggedIn()) {
    const params = new URLSearchParams(window.location.search)
    if (params.get('hub_token')) {
      return (
        <div className="flex min-h-screen items-center justify-center bg-dark-bg text-dark-text">
          <div className="flex flex-col items-center gap-3">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-accent-blue border-t-transparent" />
            <span className="text-sm text-dark-text-secondary">SSO 登录中...</span>
          </div>
        </div>
      )
    }
    return <Navigate to={`/login${window.location.search}`} replace />
  }
  return <>{children}</>
}
