import { useState } from 'react';
import { cn } from 'cn';
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

const NAV = [
  { to: '/', label: '对话', end: true },
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
        <Button variant="outline" size="sm" className="h-7 text-xs">
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
        <TokenDialog />
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
