import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { APP_BASE } from './lib/api'
import './index.css'

// 初始化主题，避免加载时闪烁
document.documentElement.classList.remove('light')
if (localStorage.getItem('theme') === 'dark') {
  document.documentElement.classList.add('dark')
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter basename={APP_BASE || undefined}>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
