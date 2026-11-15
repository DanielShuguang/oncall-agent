/** 窄屏会话抽屉的焦点循环（ADR-0077）。 */
export function nextFocusTarget(
  elements: readonly HTMLElement[],
  active: Element | null,
  shift: boolean,
): HTMLElement | null {
  if (elements.length === 0) return null;
  const first = elements[0];
  const last = elements[elements.length - 1];
  if (!active || !elements.includes(active as HTMLElement)) {
    return shift ? last : first;
  }
  if (shift && active === first) return last;
  if (!shift && active === last) return first;
  return null;
}
