# web · React 19 + Vite + Tailwind CSS

## 启动

需要 Node ≥ 22.12 与 pnpm 10（Vite 8 / Vitest 5 / React Router 8 的下限，见 [ADR-0007](../docs/decisions/0007-dependency-versions.md)）。

```bash
pnpm install
pnpm dev          # http://127.0.0.1:5173
```

`/api` 已代理到 `http://127.0.0.1:8000`（见 `vite.config.ts`）。

## 结构

```
src/
├─ main.tsx               入口（Router）
├─ App.tsx                外壳与路由
├─ api/client.ts          请求封装（类型后续由 gen:api 生成）
├─ components/ui/          shadcn/ui 组件（源码复制，见 ADR-0008）
├─ styles/global.css       Tailwind 入口 + @theme 令牌 + shadcn 令牌映射
└─ features/
   ├─ chat/
   │  ├─ types.ts         事件与视图模型（对齐 server/app/schemas/event.py）
   │  ├─ machine.ts       状态机 + 事件归约器（纯函数，可测）
   │  ├─ machine.test.ts  转移表与归约的回归测试
   │  ├─ stream.ts        SSE 客户端（fetch + ReadableStream）
   │  ├─ store.ts         Zustand，只管当前一轮运行态
   │  └─ ChatPage.tsx     对话界面
   └─ console/
      └─ ConsolePage.tsx  管理后台（占位，W5 实现）
```

## 约定

- **状态机是唯一的状态来源**：不要在组件里用 `useState` 拼 `loading/error` 之类的布尔组合
- **样式只用 Tailwind**：颜色/字号取自 `global.css` 的 `@theme` 令牌（`bg-panel`、`text-muted`），
  不写内联 `style`、不新增全局类；条件样式用 `cn()` 拼接
- **组件层用 shadcn**：`pnpm dlx shadcn@latest add <name>`，只加用得到的（见 [ADR-0008](../docs/decisions/0008-shadcn-components.md)）；
  组件认的 `--primary/--background` 在 `global.css` 里映射到项目令牌，**不要改组件里的色值**
- 未知事件类型必须忽略，不能 throw（契约要求）
- 流式高频更新要合并（W5 用 rAF 批量提交），避免每帧 re-render
- 事件里的 `seq` 要存下来，断线续传依赖它

## 代码约束

| 命令                     | 作用                                |
| ------------------------ | ----------------------------------- |
| `pnpm lint`              | oxlint，规则见 `.oxlintrc.json`     |
| `pnpm lint:fix`          | oxlint `--fix`                      |
| `pnpm format`            | oxfmt 就地格式化（`.oxfmtrc.json`） |
| `pnpm format:check`      | 只检查格式，CI 用                   |
| `pnpm exec tsc --noEmit` | 类型检查（oxc 不做类型检查）        |

行宽 100、单引号，与仓库根目录 `.editorconfig` 一致。

## 类型同源

```bash
# 后端启动后
pnpm gen:api      # 生成 src/api/generated.ts
```

当前 `types.ts` 是手写的等价类型；W1 D2 接上生成后删除重复定义。

## 待办（对应路线图）

| 事项                                                      | 里程碑 |
| --------------------------------------------------------- | ------ |
| 审批卡接通 `/approvals/{id}/resolve`                      | W3 D14 |
| 运行详情 / 回放页                                         | W4 D20 |
| 知识库 / 工具 / 权限 / 成本 四个后台页（含自写表格/表单） | W5     |
| 长会话虚拟滚动 + 流式 rAF 合并                            | W5 D24 |

> 断线续传已在 W1 D4 接通：`features/chat/store.ts` 的 `catchUp` 按 `lastSeq`
> 补拉 `/runs/{id}/events`，run 仍在 running 时轮询到终态。
