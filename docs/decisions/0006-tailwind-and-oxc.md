# ADR-0006 · 前端样式用 Tailwind CSS，代码约束用 oxc

- 状态：已采纳（组件层部分由 [ADR-0008](0008-shadcn-components.md) 修订：改用 shadcn/ui，其余结论不变）
- 日期：2026-11-08
- 影响范围：`web/`（样式体系、lint/format 工具链）、`Makefile`、`scripts/dev.ps1`、CI、`docs/07`

## 背景

骨架阶段前端用的是 Ant Design 5 + Biome：

- **Ant Design** 提供了按钮、输入框、标签、卡片、Tabs，但项目真正需要的是「三屏对话 + 四个后台页」，
  且大量状态语义样式（工具卡片是读还是写、审批卡风险等级、步骤状态）本来就得自己写。
  结果是「组件库的 token」和「自己的 CSS 变量」两套设计语言并存，改一个颜色要同时翻 `ConfigProvider` 和 `global.css`。
- **Biome** 一个工具同时做 lint 和 format，换来的是「想只换 lint 或只换 format 就换不了」，
  而且当时没有落 `biome.json`，实际跑的是默认规则集，约束力接近零。

两条约束来自项目自身：

1. 6 周里样式必须**可预测**：设计令牌一处定义，组件里只有 utility，不要出现「覆盖组件库默认样式」的补丁。
2. 工具链要能逐层替换：lint 规则、格式化风格、类型检查各自独立，出问题只换一层。

## 方案对比

### 样式

| 方案 | 优点 | 缺点 |
|---|---|---|
| Ant Design 5 | 开箱组件多，后台表格/表单省事 | CSS-in-JS 与 Tailwind preflight 抢优先级；换肤要改两层；与"自己的色彩语义"重复 |
| **Tailwind CSS 4**（采纳） | 令牌集中在 `@theme`；utility 即文档；产物只含用到的类 | 复杂组件（表格、日期选择）要自己写；HTML 里 class 较长 |
| CSS Modules / styled-components | 作用域隔离好 | 与 utility 体系并存会出现第二套令牌，项目里没有第二套样式的需求 |
| 纯手写 CSS 变量 | 零依赖 | 没有响应式/状态变体的系统化表达，6 周内会写成一堆 `.oncall-xxx` |

### 代码约束

| 方案 | 优点 | 缺点 |
|---|---|---|
| Biome（原方案） | 一个二进制搞定 lint + format | 规则集与 ESLint 生态不兼容；格式与 lint 绑死 |
| **oxc：oxlint + oxfmt**（采纳） | Rust 实现、毫秒级；规则名兼容 ESLint，迁移成本低；lint 与 format 拆成两个命令，可分别升级 | `oxfmt` 仍是 0.x，格式风格偶有变动；类型感知规则需要额外组件 |

## 决策

1. 样式**只用** Tailwind CSS 4，经 `@tailwindcss/vite` 接入，入口 `src/styles/global.css`，
   设计令牌写在 `@theme`；移除 `antd` 依赖。
2. 通用原语（Button / Tag / Card / Alert / Tabs）收敛到 `src/components/ui.tsx`，用 Tailwind 写。
3. 代码约束改为 oxc 系：`oxlint` 查问题（`web/.oxlintrc.json`），`oxfmt` 格式化（`web/.oxfmtrc.json`）；
   移除 `@biomejs/biome`，`make fmt` / `make lint` 与 CI 同步改。
4. 类型检查仍由 `tsc --noEmit` 负责，oxc 不替代它。

## 后果

- 好处：换肤只改 `@theme`；组件样式没有「优先级战争」；lint 毫秒级，pre-commit 或 CI 里几乎无感。
- 代价：
  - 后台的表格、日期选择、上传要自己写（W5 的工作量上升，已在 `docs/10` 排期里预留）。
  - `oxfmt` 处于 0.x，升级前要先跑 `pnpm format:check` 看 diff 是否可接受。
  - 全员必须遵守「不写内联 style、不加全局类」，否则 utility 体系会退化；这条写进 `AGENTS.md` §6。
- 回滚方式：`git revert` 本 ADR 对应的两个提交，`pnpm add antd @biomejs/biome` 并恢复脚本；
  因为样式都收敛在 `ui.tsx` 与 `@theme`，回滚面可控。
