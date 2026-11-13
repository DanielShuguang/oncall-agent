import { describe, expect, it } from 'vitest';

import { asTruncatedPreview } from './timelinePayload';

describe('asTruncatedPreview', () => {
  it('accepts the server wrapper', () => {
    const value = { truncated: true, original_chars: 5000, preview: 'x'.repeat(1024) };
    expect(asTruncatedPreview(value)).toEqual(value);
  });

  it('rejects primitives and partial lookalikes', () => {
    expect(asTruncatedPreview(null)).toBeNull();
    expect(asTruncatedPreview('truncated')).toBeNull();
    expect(asTruncatedPreview({ truncated: true, preview: 'x' })).toBeNull();
    expect(asTruncatedPreview({ truncated: false, original_chars: 1, preview: 'x' })).toBeNull();
    expect(asTruncatedPreview({ truncated: true, original_chars: 1, preview: 3 })).toBeNull();
  });
});
