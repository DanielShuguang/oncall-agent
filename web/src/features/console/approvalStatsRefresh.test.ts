import { describe, expect, it } from 'vitest';
import {
  APPROVAL_STATS_AUTO_REFRESH_STORAGE_KEY,
  APPROVAL_STATS_REFRESH_INTERVAL_STORAGE_KEY,
  APPROVAL_STATS_REFRESH_INTERVAL_OPTIONS,
  DEFAULT_APPROVAL_STATS_REFRESH_SECONDS,
  clearApprovalStatsAutoRefresh,
  clearApprovalStatsRefreshInterval,
  formatStatsUpdatedAt,
  readApprovalStatsAutoRefresh,
  readApprovalStatsRefreshInterval,
  shouldAutoRefresh,
  writeApprovalStatsAutoRefresh,
  writeApprovalStatsRefreshInterval,
} from './approvalStatsRefresh';

describe('approvalStatsRefresh', () => {
  it('默认 30 秒，只提供 15/30/60 三档', () => {
    expect(DEFAULT_APPROVAL_STATS_REFRESH_SECONDS).toBe(30);
    expect(APPROVAL_STATS_REFRESH_INTERVAL_OPTIONS).toEqual([15, 30, 60]);
  });

  it('只在页面可见时自动刷新', () => {
    expect(shouldAutoRefresh('visible')).toBe(true);
    expect(shouldAutoRefresh('hidden')).toBe(false);
  });

  it('暂停后即使页面可见也不自动刷新', () => {
    expect(shouldAutoRefresh('visible', false)).toBe(false);
  });

  it('没有更新时不伪造时间', () => {
    expect(formatStatsUpdatedAt(null)).toBe('尚未更新');
    expect(formatStatsUpdatedAt(0)).toMatch(/^\d{2}:\d{2}:\d{2}$/);
  });

  it('默认开启，保存关闭后读回关闭', () => {
    const storage = new MemoryStorage();
    expect(readApprovalStatsAutoRefresh(storage)).toBe(true);

    writeApprovalStatsAutoRefresh(false, storage);
    expect(storage.getItem(APPROVAL_STATS_AUTO_REFRESH_STORAGE_KEY)).toBe('off');
    expect(readApprovalStatsAutoRefresh(storage)).toBe(false);

    writeApprovalStatsAutoRefresh(true, storage);
    expect(readApprovalStatsAutoRefresh(storage)).toBe(true);
  });

  it('损坏值按默认开启处理，不可用存储不抛错', () => {
    const storage = new MemoryStorage();
    storage.setItem(APPROVAL_STATS_AUTO_REFRESH_STORAGE_KEY, 'unexpected');
    expect(readApprovalStatsAutoRefresh(storage)).toBe(true);

    const broken = {
      getItem: () => {
        throw new Error('blocked');
      },
      setItem: () => {
        throw new Error('blocked');
      },
      removeItem: () => {
        throw new Error('blocked');
      },
    };
    expect(readApprovalStatsAutoRefresh(broken)).toBe(true);
    expect(() => writeApprovalStatsAutoRefresh(false, broken)).not.toThrow();
    expect(() => clearApprovalStatsAutoRefresh(broken)).not.toThrow();
  });

  it('清除偏好后回到默认开启', () => {
    const storage = new MemoryStorage();
    writeApprovalStatsAutoRefresh(false, storage);
    clearApprovalStatsAutoRefresh(storage);
    expect(readApprovalStatsAutoRefresh(storage)).toBe(true);
  });

  it('刷新间隔默认 30 秒，只接受 15/30/60', () => {
    const storage = new MemoryStorage();
    expect(readApprovalStatsRefreshInterval(storage)).toBe(30);

    writeApprovalStatsRefreshInterval(60, storage);
    expect(readApprovalStatsRefreshInterval(storage)).toBe(60);
    storage.setItem(APPROVAL_STATS_REFRESH_INTERVAL_STORAGE_KEY, '45');
    expect(readApprovalStatsRefreshInterval(storage)).toBe(30);
    storage.setItem(APPROVAL_STATS_REFRESH_INTERVAL_STORAGE_KEY, 'broken');
    expect(readApprovalStatsRefreshInterval(storage)).toBe(30);
  });

  it('清除刷新间隔后回到默认 30 秒', () => {
    const storage = new MemoryStorage();
    writeApprovalStatsRefreshInterval(15, storage);
    clearApprovalStatsRefreshInterval(storage);
    expect(readApprovalStatsRefreshInterval(storage)).toBe(30);
  });
});

class MemoryStorage {
  private readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }
}
