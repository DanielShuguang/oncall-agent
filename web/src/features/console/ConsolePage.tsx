import { lazy, Suspense, type ComponentType, type LazyExoticComponent } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

const PAGES: Record<string, { component: LazyExoticComponent<ComponentType>; loading: string }> = {
  kb: { component: lazy(() => import('./KbPage')), loading: '加载知识库…' },
  tools: { component: lazy(() => import('./ToolsPage')), loading: '加载工具注册…' },
  perms: { component: lazy(() => import('./PermsPage')), loading: '加载权限矩阵…' },
  approvals: { component: lazy(() => import('./ApprovalsPage')), loading: '加载审批中心…' },
  cost: { component: lazy(() => import('./CostPage')), loading: '加载成本页…' },
};

const PANELS = [
  {
    key: 'kb',
    label: '知识库',
    title: '知识库管理（上传 / 列表 / 切片预览 / 重建索引）',
    milestone: 'W5 D21',
  },
  {
    key: 'tools',
    label: '工具',
    title: '工具注册与试调用（schema 查看、启用开关、试调用）',
    milestone: 'W5 D22',
  },
  { key: 'perms', label: '权限', title: '角色 × 工具权限矩阵', milestone: 'W5 D23' },
  { key: 'approvals', label: '审批', title: '审批中心（待办 / 已办）', milestone: 'W5 D23' },
  {
    key: 'cost',
    label: '成本',
    title: '成本看板（按天 / 模型 / 用户聚合 + Top run）',
    milestone: 'W4 D19',
  },
];

function PanelContent({ panelKey }: { panelKey: string }) {
  const page = PAGES[panelKey];
  if (!page) return null;
  const Component = page.component;
  return (
    <Suspense fallback={<div className="p-4 text-xs text-muted-foreground">{page.loading}</div>}>
      <Component />
    </Suspense>
  );
}

export default function ConsolePage() {
  const location = useLocation();
  const navigate = useNavigate();
  const active = location.pathname.split('/')[2] || 'kb';

  return (
    <div className="flex-1 overflow-y-auto p-4">
      <Tabs
        value={active}
        onValueChange={(next) => {
          navigate(`/console/${next}`);
        }}
      >
        <TabsList variant="line">
          {PANELS.map((panel) => (
            <TabsTrigger key={panel.key} value={panel.key}>
              {panel.label}
            </TabsTrigger>
          ))}
        </TabsList>

        {PANELS.map((panel) => (
          <TabsContent key={panel.key} value={panel.key} className="pt-4">
            {PAGES[panel.key] ? (
              <PanelContent panelKey={panel.key} />
            ) : (
              <Card className="gap-0 py-0">
                <CardContent className="space-y-2 p-4">
                  <div className="text-sm">
                    <strong>{panel.title}</strong> 正在建设中，计划于{' '}
                    <Badge variant="secondary">{panel.milestone}</Badge> 完成。
                  </div>
                  <div className="text-sm text-muted-foreground">
                    设计见 docs/07-frontend-design.md 与 docs/10-roadmap-6weeks.md。
                  </div>
                </CardContent>
              </Card>
            )}
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
