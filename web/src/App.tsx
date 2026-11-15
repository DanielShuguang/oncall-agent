import { useState } from 'react';
import { cn } from 'cn';
import { MessagesSquare } from 'lucide-react';
import { NavLink, Navigate, Route, Routes } from 'react-router';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { getToken, setToken } from './api/client';
import ChatPage from './features/chat/ChatPage';
import ConsolePage from './features/console/ConsolePage';
import RunDetailPage from './features/runs/RunDetailPage';
import RunsPage from './features/runs/RunsPage';

const NAV = [
  { to: '/', label: '对话', end: true },
  { to: '/runs', label: '运行', end: false },
  { to: '/console/kb', label: '管理后台', end: false },
];

/** W1 本地 JWT：没有登录页，运维签发后粘进 localStorage（docs/03 §0）。 */
function TokenDialog() {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState('');
  const [hasToken, setHasToken] = useState(() => Boolean(getToken()));
  const [saved, setSaved] = useState(false);

  const onOpenChange = (next: boolean) => {
    setOpen(next);
    if (next) {
      setValue(getToken() ?? '');
      setSaved(false);
    }
  };

  const save = () => {
    setToken(value.trim());
    setHasToken(Boolean(value.trim()));
    setSaved(true);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="h-7 shrink-0 text-xs">
          {hasToken ? '已登录' : '设置 Token'}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>本地访问 Token</DialogTitle>
          <DialogDescription>
            v1 不接 SSO，token 由运维命令签发（默认 8 小时有效）：
            <code className="mt-2 block rounded-md border bg-canvas px-2 py-1.5 font-mono text-xs break-all">
              cd server && uv run python -m app.cli token --user u_102 --roles employee
            </code>
          </DialogDescription>
        </DialogHeader>
        <Input
          value={value}
          aria-label="访问 Token"
          placeholder="粘贴 JWT…"
          className="font-mono text-xs"
          onChange={(e) => setValue(e.target.value)}
        />
        <DialogFooter>
          <Button onClick={save}>保存</Button>
        </DialogFooter>
        {saved && <p className="text-xs text-ok">已保存，下一次请求生效。</p>}
      </DialogContent>
    </Dialog>
  );
}

export default function App() {
  return (
    <div className="flex h-full w-full flex-col bg-canvas">
      <header className="z-20 flex flex-wrap items-center gap-x-4 gap-y-2 border-b bg-panel/95 px-4 py-2.5 shadow-xs backdrop-blur sm:px-6">
        <div className="flex items-center gap-2.5">
          <span className="grid size-8 place-items-center rounded-lg bg-brand text-primary-foreground shadow-sm">
            <MessagesSquare className="size-4" />
          </span>
          <div className="leading-tight">
            <h1 className="m-0 text-[15px] font-semibold tracking-tight">OnCall</h1>
            <p className="m-0 text-[11px] text-muted-foreground">企业智能体工作台</p>
          </div>
        </div>
        <Badge
          variant="outline"
          className="hidden border-brand/20 bg-brand/10 text-brand sm:inline-flex"
        >
          私有化部署
        </Badge>
        <nav className="ml-auto flex items-center gap-1 rounded-lg bg-canvas p-1 text-[13px]">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  'rounded-md px-3 py-1.5 transition-colors',
                  isActive
                    ? 'bg-panel font-medium text-brand shadow-xs'
                    : 'text-muted-foreground hover:text-foreground',
                )
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <TokenDialog />
      </header>

      <main className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <Routes>
          <Route path="/" element={<ChatPage />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/:id" element={<RunDetailPage />} />
          <Route path="/console/*" element={<ConsolePage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
