# web · React 19 + Vite + Ant Design

## 启动

```bash
pnpm install
pnpm dev          # http://127.0.0.1:5173
```

`/api` 已代理到 `http://127.0.0.1:8000`（见 `vite.config.ts`）。

## 结构

```
src/
├─ main.tsx               入口（ConfigProvider + Router）
├─ App.tsx                外壳与路由
├─ api/client.ts          请求封装（类型后续由 gen:api 生成）
├─ styles/global.css      设计变量与基础样式
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
- 未知事件类型必须忽略，不能 throw（契约要求）
- 流式高频更新要合并（W5 用 rAF 批量提交），避免每帧 re-render
- 事件里的 `seq` 要存下来，断线续传依赖它

## 类型同源

```bash
# 后端启动后
pnpm gen:api      # 生成 src/api/generated.ts
```

当前 `types.ts` 是手写的等价类型；W1 D2 接上生成后删除重复定义。

## 待办（对应路线图）

| 事项 | 里程碑 |
|---|---|
| 接 `/runs/{id}/events` 补拉 + 断线重连 | W1 D4 |
| 审批卡接通 `/approvals/{id}/resolve` | W3 D14 |
| 运行详情 / 回放页 | W4 D20 |
| 知识库 / 工具 / 权限 / 成本 四个后台页 | W5 |
| 长会话虚拟滚动 + 流式 rAF 合并 | W5 D24 |
