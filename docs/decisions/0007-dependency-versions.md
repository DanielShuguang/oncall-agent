# ADR-0007 · 依赖版本策略：跟最新，TypeScript 用 6.0（7.0 暂缓）

- 状态：已采纳（2026-11-08 修订：TypeScript 5.9.3 → 6.0.3）
- 日期：2026-11-08
- 影响范围：`web/package.json`、`web/tsconfig.json`、`web/pnpm-lock.yaml`、CI、`docs/11`、`web/README.md`

## 背景

骨架初始化时前端依赖落后于生态：Vite 6 / Vitest 2 / TypeScript 5.7 / React Router 6。要求是「用最新版本」，
但 `pnpm up --latest` 不能无脑跑：一处不兼容会让类型同源流水线（`docs/07` §8）直接断掉。

## 决策

### 1. 采用的最新主版本（均已在本仓库验证）

| 包 | 版本 | 备注 |
|---|---|---|
| vite | 8.3.6 | 构建 ~150ms；`@tailwindcss/vite` 已声明支持 `^8` |
| vitest | 5.1.0 | 要求 Node ≥22.12 |
| @vitejs/plugin-react | 6.2.1 | 要求 Vite ^8；oxc/babel 相关 peer 均为 optional |
| typescript | 6.0.3 | 过渡版，仍带 JS 编译器 API；7.0 暂缓（见 §2） |
| react / react-dom | 19.3.1 | |
| react-router | 8.5.1 | **从 `react-router-dom` 迁到 `react-router`**（v8 不再发布 dom 包）；要求 Node ≥22.22 |
| echarts / echarts-for-react | 6.1.0 / 3.0.6 | |
| @tanstack/react-query | 5.107.1 | |
| zustand | 5.1.0 | |
| openapi-typescript | 7.13.0 | 类型同源流水线的 codegen |
| tailwindcss / @tailwindcss/vite | 4.3.5 | |
| oxlint / oxfmt | 1.92.0 / 0.77.0 | |

### 2. TypeScript 用 6.0.3，暂不使用 7.0.2

TypeScript 7 是 Go 原生编译器，`typescript` 包只暴露 `getExePath` 等 2 个导出，**没有编译器 API**。
`openapi-typescript@7.13.0` 依赖 `ts.factory.createKeywordTypeNode`，在 TS 7 下启动即崩：

```
TypeError: Cannot read properties of undefined (reading 'createKeywordTypeNode')
  at openapi-typescript/dist/lib/ts.mjs:11:28
```

而「Pydantic → OpenAPI → openapi-typescript → `src/api/generated.ts`」是文档写死的类型同源方案，
不能让 codegen 失效。

**TS 6.0 正好是安全落点**：它是 7.0 的过渡版，仍基于 JS 代码库、保留完整编译器 API，
所以 `openapi-typescript` 在 6.0.3 下已验证可正常生成（用本地 OpenAPI 文档实测）。
6.0.3 上 `tsc --noEmit` / `tsc -b` / `vite build` 全部通过。

- 升级 TS 7 的前置条件（任一满足即可）：`openapi-typescript` 适配 TS 7 的 API，或改用不依赖 TS JS API 的生成器
- 升级时同步改本 ADR、`docs/11` 与 `web/README.md`

### 3. TS 6.0 破坏性默认值与本仓库的处理

| TS 6.0 变化 | 本仓库处理 |
|---|---|
| `types` 默认 `[]`（不再自动加载所有 `@types/*`） | 显式声明 `"types": ["vite/client"]` |
| `baseUrl` 废弃（7.0 移除） | **删除 `baseUrl`**，`paths` 直接写相对 tsconfig 的 `./src/*`；没有用 `ignoreDeprecations` 掩盖 |
| `target: es5`、`downlevelIteration`、`outFile`、`module amd/umd/systemjs`、`moduleResolution node10/classic` 废弃 | 本仓库原本就没用这些选项 |
| `esModuleInterop` / `allowSyntheticDefaultImports` 不能再设为 `false`；`alwaysStrict` 恒开 | 未设置，行为与之前一致 |
| `strict` / `module: esnext` / 当年 ES target 成为默认值 | 本来就显式写了 `strict: true`、`module: ESNext`、`target: ES2022` |
| `dom.iterable` 并入 `dom` | `lib` 从 `["ES2022", "DOM", "DOM.Iterable"]` 简化为 `["ES2022", "DOM"]` |
| `noUncheckedSideEffectImports` 默认 `true` | `import './styles/global.css'` 由 `vite/client` 的 `*.css` 声明满足，类型检查通过 |
| 泛型推断更严格（`this`-less 函数、JSX 回调） | 本仓库代码无新增类型错误 |
| `openapi-typescript` 的 peer 仍写 `typescript@^5.x` | `pnpm.peerDependencyRules.allowedVersions` 放行 `6`，并注明理由（实测可用） |

### 4. 运行时下限

React Router 8 要求 Node ≥22.22、Vitest 5 要求 ≥22.12，因此统一到 **Node 24 / pnpm 10**
（`packageManager` 字段声明 pnpm 10.34.3，CI 同步）。

## 后果

- 好处：构建与 typecheck 显著变快；依赖与生态同步，减少「文档写 v6、实际 v8」的认知负担。
- 代价：
  - Node 下限从 20 提到 22.22，旧开发机需要升级；CI 已同步到 24。
  - TypeScript 落后 TS 7 一个大版本；`pnpm outdated` 里会一直看到它，这是有明确解除条件的债。
  - TS 6 的默认值调整已经落在 `tsconfig.json` 里（`types` 显式、无 `baseUrl`），迁移到 7.0 时主要剩编译器 API 依赖问题。
  - `react-router-dom` 迁移改了 2 个 import（`main.tsx`、`App.tsx`），后续新增路由统一从 `react-router` 导入。
