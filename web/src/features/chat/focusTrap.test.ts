import { describe, expect, it } from 'vitest';

import { nextFocusTarget } from './focusTrap';

const first = {} as HTMLElement;
const middle = {} as HTMLElement;
const last = {} as HTMLElement;
const outside = {} as HTMLElement;

describe('nextFocusTarget', () => {
  it('wraps forward from the last to the first', () => {
    expect(nextFocusTarget([first, middle, last], last, false)).toBe(first);
  });

  it('wraps backward from the first to the last', () => {
    expect(nextFocusTarget([first, middle, last], first, true)).toBe(last);
  });

  it('pulls focus into the drawer when it is outside', () => {
    expect(nextFocusTarget([first, middle, last], outside, false)).toBe(first);
    expect(nextFocusTarget([first, middle, last], outside, true)).toBe(last);
  });

  it('leaves normal movement to the browser', () => {
    expect(nextFocusTarget([first, middle, last], middle, false)).toBeNull();
    expect(nextFocusTarget([], null, false)).toBeNull();
  });
});
