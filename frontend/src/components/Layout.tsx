import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import TopBar from './TopBar'
import { NotificationProvider } from './NotificationProvider'

export default function Layout() {
  const isPortal = window !== window.parent
  return (
    <NotificationProvider>
      <div className="flex h-screen overflow-hidden">
        {!isPortal && <Sidebar />}
        <div className="flex flex-1 flex-col overflow-hidden">
          {!isPortal && <TopBar />}
          <main className={`flex-1 overflow-y-auto ${isPortal ? 'p-4' : 'p-6'}`}>
            <Outlet />
          </main>
        </div>
      </div>
    </NotificationProvider>
  )
}
