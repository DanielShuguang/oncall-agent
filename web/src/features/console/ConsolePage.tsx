import { Card, Tabs, Typography } from 'antd';

const { Paragraph } = Typography;

const placeholder = (title: string, milestone: string) => (
  <Card>
    <Paragraph>
      <strong>{title}</strong> 正在建设中，计划于 <code>{milestone}</code> 完成。
    </Paragraph>
    <Paragraph type="secondary">
      设计见 docs/07-frontend-design.md 与 docs/10-roadmap-6weeks.md。
    </Paragraph>
  </Card>
);

export default function ConsolePage() {
  return (
    <div className="oncall-scroll">
      <Tabs
        defaultActiveKey="kb"
        items={[
          {
            key: 'kb',
            label: '知识库',
            children: placeholder('知识库管理（上传 / 列表 / 切片预览 / 重建索引）', 'W5 D21'),
          },
          {
            key: 'tools',
            label: '工具',
            children: placeholder('工具注册与试调用（schema 编辑、启用开关）', 'W5 D22'),
          },
          {
            key: 'perms',
            label: '权限',
            children: placeholder('角色 × 工具权限矩阵', 'W5 D23'),
          },
          {
            key: 'approvals',
            label: '审批',
            children: placeholder('审批中心（待办 / 已办）', 'W5 D23'),
          },
          {
            key: 'cost',
            label: '成本',
            children: placeholder('成本看板（按天 / 模型 / 用户聚合 + Top run）', 'W4 D19'),
          },
        ]}
      />
    </div>
  );
}
