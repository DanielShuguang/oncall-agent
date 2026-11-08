import { useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

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
    title: '工具注册与试调用（schema 编辑、启用开关）',
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

export default function ConsolePage() {
  const [active, setActive] = useState('kb');

  return (
    <div className="flex-1 overflow-y-auto p-4">
      <Tabs value={active} onValueChange={setActive}>
        <TabsList variant="line">
          {PANELS.map((panel) => (
            <TabsTrigger key={panel.key} value={panel.key}>
              {panel.label}
            </TabsTrigger>
          ))}
        </TabsList>

        {PANELS.map((panel) => (
          <TabsContent key={panel.key} value={panel.key} className="pt-4">
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
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
