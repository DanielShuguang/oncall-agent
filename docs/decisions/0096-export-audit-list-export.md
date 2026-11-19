# ADR-0096：导出审计列表 CSV 导出

- 状态：已采纳
- 日期：2026-11-19
- 相关：[ADR-0094](0094-export-download-audit.md)、[ADR-0095](0095-export-audit-retention.md)

## 背景

ADR-0094 让 6 个 CSV 端点记录下载审计，并提供只读列表；ADR-0095 为这张表加了独立保留期。
但审计记录本身只能在管理页逐页看：要交给审计/合规做离线核对，或按用户/资源/日期拉一份
快照时，没有导出入口。管理页的「加载更多」也不是归档格式，无法长期保存。

导出审计也是只读操作，但它读取的是治理证据，仍应留下「谁在什么时候、用什么过滤条件、
导出了多少条审计记录」的证据；否则会出现「审计日志被导出过，但没有任何记录」的缺口。

## 备选方案

| 方案 | 结论 |
|---|---|
| 不提供导出，只让管理员在页面看 | 不满足离线核对；页面不是可归档格式 |
| 直接查数据库导出 | 绕过权限与审计，部署后不可控 |
| 异步生成 + 下载中心 | 需要任务表/对象存储/回调，当前规模不值 |
| 同步 CSV，最多 5000 行，导出本身也写审计 | **采纳**，与其余 6 个导出保持同一套契约 |

## 决策

1. **新增第 7 种资源** `export_audits`；`export_audits.resource` 的 CHECK 扩展，迁移
   `0024` 只 drop/create 该 CHECK，不改字段和索引；downgrade 先删除 `export_audits`
   资源的记录，否则旧 6 值 CHECK 无法建立。
2. **接口**：`GET /admin/export-audits/export`，与列表相同的 `user_id`、`resource`、
   `created_from/to` 过滤；不接受 `cursor`/`limit`，一次最多 5000 行。
3. **CSV 列**：`created_at,user_id,resource,row_count,truncated,filters`；`filters` 用
   JSON 字符串保存，复用 `csv_document` 的 BOM/CRLF/公式防护。
4. **自身也写审计**：导出成功后写一条 `resource=export_audits` 的记录，`filters` 记录
   本次过滤，`row_count` 是实际导出行数，`truncated` 标记是否被 5000 行截断。写入失败
   返回 503，不返回无法留痕的文件。
5. **截断语义**：查询 `5000+1` 行判断截断，返回前 5000 行；响应头
   `X-Export-Count`/`X-Export-Truncated`，文件名 `export-audits-{UTC}.csv`，`Cache-Control: no-store`。
6. **不做**：导出文件内容回放、按审计记录再导出单条、异步任务、XLSX、下载中心。
7. **保留**：导出的审计记录仍按 ADR-0095 的 365 天统一清理；不对 `export_audits`
   单独设更短保留期。

## 后果

- 导出审计列表也会多一条「导出审计」记录；这是预期行为，不是重复计数，页面按
  `resource` 过滤可以单独查看。
- 单次最多 5000 行；需要全量归档时按日期/用户分片导出。
- 迁移 `0024` 只改 CHECK，旧数据无需回填；降级时如果已经存在 `export_audits` 记录，
  downgrade 会删除这些记录再恢复 6 值 CHECK（降级即放弃「导出审计自身导出」能力；
  这是破坏性降级的明确数据损失，不静默保留旧 CHECK）。
- 导出是同步读；大表下仍是 5000 行上限，没有游标导出。

## 验证

- 后端：`server/tests/test_export_audits.py` 新增自身导出用例，断言 CSV 表头、行数、
  响应头与新增的 `export_audits` 审计行；`test_store_contract` 覆盖第 7 种资源的内存/PG
  写入；迁移 `0024` 往返通过（含先插入 `export_audits` 行再 downgrade 的场景）。
- 前端：`web/src/api/exportAudits.test.ts` 新增导出 URL/响应头用例；页面「导出 CSV」
  成功后刷新列表，能看到自身审计记录。
- 默认 527+40（tests=567）/ PG-only 564+3 / PG+Redis 567；迁移 `0024` 往返通过；
  `ruff check` / `ruff format --check` 207 files、`mypy app` 119 files 通过。
- 前端 27 files/131 tests、`oxlint` 0/0（131 files）、`oxfmt --check` 139 files、
  `pnpm build` 2938 modules 通过。

## 待定

- 审计日志的「按行号增量导出」与游标导出；
- 导出成功后由前端确认下载完成（多副本写入顺序不保证）；
- 审计 CSV 的签名/哈希归档；
- 导出审计自身的更细权限（当前只要求 admin）。
