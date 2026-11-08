import { cn } from 'cn';
import { NavLink, Navigate, Route, Routes } from 'react-router';
import { Badge } from '@/components/ui/badge';
import ChatPage from './features/chat/ChatPage';
import ConsolePage from './features/console/ConsolePage';

const NAV = [
  { to: '/', label: '对话', end: true },
  { to: '/console/kb', label: '管理后台', end: false },
];

export default function App() {
  return (
    <div className="mx-auto flex h-full w-full max-w-4xl flex-col bg-panel md:border-x">
      <header className="flex items-center gap-3 border-b px-4 py-3">
        <h1 className="m-0 text-[15px] font-semibold">OnCall</h1>
        <Badge variant="outline" className="border-brand/20 bg-brand/10 text-brand">
          私有化企业智能体
        </Badge>
        <nav className="ml-auto flex gap-4 text-[13px]">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  'transition-colors hover:text-brand',
                  isActive ? 'font-medium text-brand' : 'text-muted-foreground',
                )
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className="flex min-h-0 flex-1 flex-col">
        <Routes>
          <Route path="/" element={<ChatPage />} />
          <Route path="/console/*" element={<ConsolePage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
