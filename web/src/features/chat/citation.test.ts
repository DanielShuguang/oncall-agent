import { describe, expect, it } from 'vitest';
import type { KbPreview } from '@/api/kb';
import { describePreview } from './citation';
import type { Citation } from './types';

const CITATION: Citation = {
  chunk_id: 12,
  document_id: 'doc_1',
  ord: 3,
  title: 'VPN 连接失败排查指南',
  heading: 'VPN > 快速判断',
  snippet: 'VPN 连不上时先确认三件事……',
  page: null,
};

function preview(overrides: Partial<KbPreview> = {}): KbPreview {
  return {
    document: {
      id: 'doc_1',
      title: CITATION.title,
      source: 'vpn-guide.pdf',
      version: null,
      checksum: 'abc',
      chunk_count: 2,
      status: 'indexed',
      created_at: '2026-11-09T00:00:00Z',
    },
    chunks: [
      { chunk_id: 11, ord: 2, heading: 'VPN > 快速判断', content: '第一段', page: null },
      { chunk_id: 12, ord: 3, heading: 'VPN > 快速判断', content: '第二段', page: null },
    ],
    focused_chunk_id: 12,
    total_chunks: 2,
    truncated: false,
    ...overrides,
  };
}

describe('引用预览定位说明', () => {
  it('命中引用段时给出段号', () => {
    expect(describePreview(preview(), CITATION)).toBe('共 2 段 · 已定位第 3 段');
  });

  it('原文更新导致引用失效时明说找不到，不假装定位成功', () => {
    expect(describePreview(preview({ focused_chunk_id: null }), CITATION)).toContain(
      '引用位置未找到',
    );
  });

  it('超长截断要标出来，否则读者以为看到了全文', () => {
    expect(describePreview(preview({ truncated: true }), CITATION)).toContain('超长已截断');
  });
});
