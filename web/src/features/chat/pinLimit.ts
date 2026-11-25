/** 置顶容量溢出：配置调小后，既有置顶数可能大于上限。 */
export interface PinOverflow {
  pinned: number;
  limit: number;
}

/** 只在确实超限时返回，正常/未知计数返回 null。 */
export function pinLimitOverflow(pinned: number | null, limit: number | null): PinOverflow | null {
  if (pinned === null || limit === null || limit <= 0 || pinned <= limit) return null;
  return { pinned, limit };
}
