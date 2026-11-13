/** 运行过程里被服务端裁剪的载荷（ADR-0044）。
 *
 * 参数/结果的紧凑 JSON 超过预算时，服务端返回
 * `{truncated: true, original_chars, preview}`；错误信息则是截断后的字符串。
 */

export interface TruncatedPreview {
  truncated: true;
  original_chars: number;
  preview: string;
}

/** 三个字段必须同时成立，避免把工具恰好返回的 `{truncated, preview}` 误判成包装对象。 */
export function asTruncatedPreview(value: unknown): TruncatedPreview | null {
  if (typeof value !== 'object' || value === null) return null;
  const record = value as Record<string, unknown>;
  if (
    record.truncated !== true ||
    typeof record.original_chars !== 'number' ||
    typeof record.preview !== 'string'
  ) {
    return null;
  }
  return {
    truncated: true,
    original_chars: record.original_chars,
    preview: record.preview,
  };
}
