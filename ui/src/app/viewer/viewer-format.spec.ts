import { formatCount, formatMetres, statsLine } from './viewer-format';

describe('viewer-format', () => {
  it('writes counts with separators', () => {
    expect(formatCount(1234567)).toBe('1,234,567');
  });

  it('keeps useful precision for small and large lengths', () => {
    expect(formatMetres(0.354)).toBe('0.35 m');
    expect(formatMetres(1.84)).toBe('1.8 m');
    expect(formatMetres(12.4)).toBe('12 m');
  });

  it('summarises a model in one line', () => {
    const line = statsLine({ triangles: 1200, vertices: 700, size: [0.5, 1.8, 0.3], materials: ['a', 'b'], clips: [] });
    expect(line).toBe('1,200 triangles, 700 vertices, 0.50 m × 1.8 m × 0.30 m, 2 materials');
  });

  it('says 1 material for one', () => {
    expect(statsLine({ triangles: 1, vertices: 3, size: [1, 1, 1], materials: ['x'], clips: [] })).toContain('1 material');
  });
});
