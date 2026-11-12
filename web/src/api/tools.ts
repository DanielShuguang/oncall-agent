/** 工具注册与试调用。契约见 docs/03-api-contract.md §5。 */

import { getJson } from './client';

export interface JsonSchema {
  type?: string;
  description?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  enum?: unknown[];
}

export interface ToolInfo {
  name: string;
  description: string;
  input_schema: JsonSchema;
  is_write: boolean;
  timeout_ms: number;
  /** 空数组 = 所有登录用户 */
  roles: string[];
  enabled: boolean;
  /** 代码里的默认启用状态；false 时管理页不能打开 */
  code_enabled: boolean;
  /** 本环境是否存了覆盖 */
  overridden: boolean;
  source: string;
}

export interface ToolListResponse {
  items: ToolInfo[];
}

export interface ToolOverrideSnapshot {
  enabled: boolean | null;
  roles: string[] | null;
}

export interface ToolChange {
  id: number;
  tool_name: string;
  changed_by: string;
  changed_at: string;
  source: 'tool' | 'matrix' | string;
  before: ToolOverrideSnapshot | null;
  after: ToolOverrideSnapshot | null;
}

export interface ToolHistoryResponse {
  items: ToolChange[];
}

export function getToolHistory(name: string, limit = 20): Promise<ToolHistoryResponse> {
  return getJson<ToolHistoryResponse>(
    `/admin/tools/${encodeURIComponent(name)}/history?limit=${limit}`,
  );
}

export interface ToolTestResponse {
  tool: string;
  decision: 'executed' | 'requires_approval' | 'denied' | string;
  status: string;
  result: unknown;
  error: string | null;
  error_kind: string | null;
  duration_ms: number;
  attempts: number;
}

export function listTools(): Promise<ToolListResponse> {
  return getJson<ToolListResponse>('/admin/tools');
}

export function updateTool(name: string, body: { enabled: boolean | null }): Promise<ToolInfo> {
  return getJson<ToolInfo>(`/admin/tools/${encodeURIComponent(name)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  });
}

export function testTool(name: string, args: Record<string, unknown>): Promise<ToolTestResponse> {
  return getJson<ToolTestResponse>(`/admin/tools/${encodeURIComponent(name)}/test`, {
    method: 'POST',
    body: JSON.stringify({ args }),
  });
}

/** 从 schema 生成一份能直接改的试调用参数，避免用户从空白 JSON 猜字段。 */
export function exampleArgs(schema: JsonSchema): Record<string, unknown> {
  const args: Record<string, unknown> = {};
  for (const [key, prop] of Object.entries(schema.properties ?? {})) {
    if (Array.isArray(prop.enum) && prop.enum.length > 0) {
      args[key] = prop.enum[0];
    } else if (prop.type === 'integer' || prop.type === 'number') {
      args[key] = 0;
    } else if (prop.type === 'boolean') {
      args[key] = false;
    } else if (prop.type === 'array') {
      args[key] = [];
    } else if (prop.type === 'object') {
      args[key] = {};
    } else if (key === 'owner_id') {
      // 演示数据里 u_102 有资产；只是预填，用户可改
      args[key] = 'u_102';
    } else {
      args[key] = '';
    }
  }
  return args;
}
