# ADR-0001 · 前端框架选 React 19 而非 Vue 3

- 状态：已采纳
- 日期：2026-11-08

## 背景

我 7 年前端主力是 Vue 2/3（Vue 2.6→2.7 迁移、Pinia、VueUse、UnoCSS），React 经验来自 Theia IDE 二次研发（React 18 + Electron）。
本项目是单人 6 周交付，同时要补 Python 与 Agent 工程，前端不能成为风险点。

## 方案对比

| 维度 | React 19 | Vue 3 |
|---|---|---|
| AI 交互生态 | AG-UI 官方客户端、assistant-ui、CopilotKit、MCP Apps 渲染器均 React 优先 | 需自研或依赖弱维护的社区包 |
| 目标岗位 JD | 一线 AI 前端 JD 普遍写 React；长沙 React/Vue 并存 | 长沙不吃亏 |
| 我的熟练度 | 中（Theia 实战） | **高** |
| 6 周风险 | 中低 | 低 |

## 决策

选 **React 19**。

核心理由不是"React 更好"，而是：**本项目的差异化在 Agent 运行时与工具治理，不在前端框架**。选生态更厚的一侧，可以把省下的时间投到真正加分的地方；Vue 的能力简历里已经证明过，不需要在这个项目里再证一次。

## 后果

- 正面：可直接参考 AG-UI / assistant-ui 的事件与状态设计；面试时说"React"匹配更多 JD
- 负面：前期组件写法需要适应（约 0.5 天）；失去 UnoCSS 的熟练度红利
- 缓解：UI 层用 Ant Design（我熟），样式用 CSS 变量 + 少量 Tailwind，避免从零搭设计系统

## 如果重来

如果目标是"最快出 Demo"而非"最优展示面"，Vue 3 + UnoCSS 会更快。**框架不是考点，能为选择说出理由才是。**
