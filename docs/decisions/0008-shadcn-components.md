# ADR-0008 · 组件层采用 shadcn/ui（源码复制，底座 radix-ui）

- 状态：已采纳
- 日期：2026-11-08
- 影响范围：`web/src/components/ui/*`、`web/src/styles/global.css`、`web/components.json`、`web/vite.config.ts`、`web/tsconfig.json`

## 背景

[ADR-0006](0006-tailwind-and-oxc.md) 把 antd 换成了「Tailwind + 5 个自写原语（Button/Tag/Card/Alert/Tabs）」。
对话页够用，但 `docs/10` 的 W5 后台四页需要弹窗、下拉、Select、表格、表单校验：

- 这些组件的难点不在样式，而在**焦点管理、键盘导航、屏幕阅读器**（Dialog 的焦点陷阱、Select 的 typeahead、Table 的排序语义）
- 全部自研，等于在 6 周里重写一个 Radix

## 方案对比

| 方案 | 优点 | 缺点 |
|---|---|---|
| 继续全自写 | 零依赖，样式完全可控 | Dialog/Select/Table 的 a11y 交互成本极高，容易做成「能点但不可用」 |
| antd / MUI 等运行时组件库 | 组件全、开箱即用 | 自带 CSS/CSS-in-JS，与 Tailwind preflight 抢优先级（ADR-0006 已否决） |
| **shadcn/ui（采纳）** | 源码复制进仓库；样式仍是 Tailwind；交互交给 radix-ui；可逐个组件引入 | 代码进仓库需要 review；多 radix-ui / lucide-react 依赖 |

## 决策

1. 用 shadcn CLI 4.x 添加组件，输出到 `src/components/ui/`，配置见 `web/components.json`
   （`style: new-york`、`baseColor: neutral`、`css: src/styles/global.css`、`rsc: false`）。
2. **色板只有一套**：项目自有令牌（`--color-panel/ink/line/brand/ok/warn/danger`）是唯一事实来源，
   在 `global.css` 里把 shadcn 需要的 `--background/--foreground/--primary/...` 映射过去：

   | shadcn 令牌 | 映射到 | 说明 |
   |---|---|---|
   | `--background` | `--color-panel` | 组件默认的「面板白」，不是页面底色 |
   | `--foreground` | `--color-ink` | 正文 |
   | `--card` / `--popover` | `--color-panel` | 卡片、浮层 |
   | `--primary` | `--color-brand` | 主色 |
   | `--secondary` / `--muted` | 中性灰系 | 次要按钮、禁用态 |
   | `--muted-foreground` | `--color-muted` | 次要文字 |
   | `--accent` | 品牌浅底 | hover 态 |
   | `--destructive` | `--color-danger` | 危险操作 |
   | `--border` / `--input` | `--color-line` | 边框、输入框 |
   | `--ring` | `--color-brand` | 焦点环 |

   页面底色仍是 `--color-canvas`（`bg-canvas`），由 `body` 设置。
3. `cn()` 直接用 shadcn 官方的 `cn` 包（clsx + tailwind-merge 的编译版），不再维护本地 utils。
4. **只添加用得到的组件**，不跑 `add --all`；当前已加：button、badge、card、alert、tabs、textarea、input、label、separator、table、dialog、dropdown-menu、select、tooltip
   （对话页直接用前六个，其余是 W5 后台的预置；没被 import 的组件不进产物，构建已验证 tree-shaking 生效）。
5. 生成的文件允许改，但改样式时必须走令牌（不写裸色值），并按 oxfmt 格式化后再提交。
6. `TooltipProvider` 统一在 `main.tsx` 挂一次，避免每个页面各自包一层。

## 后果

- 好处：Dialog/Select/Dropdown/Table 的行为与 a11y 由 radix-ui 保证；W5 后台可以直接拼装，不再自造轮子。
- 代价：
  - 运行时依赖增加 `radix-ui`、`lucide-react`、`class-variance-authority`；
    生产包 JS 从 270 kB → 373 kB（gzip 86 → 122 kB），CSS 14.8 → 39.8 kB（gzip 3.7 → 7.6 kB）。
  - 生成的组件代码进仓库，review 时注意别把业务逻辑写进去。
  - `AGENTS.md` 的反模式从「不许用组件库」收敛为「不许引入**自带样式**的运行时组件库」。
- 回滚方式：删除 `src/components/ui/`、`components.json`、`lib` 相关依赖，回到 ADR-0006 的自写原语；
  因为令牌仍在 `global.css`，回滚不影响配色。
