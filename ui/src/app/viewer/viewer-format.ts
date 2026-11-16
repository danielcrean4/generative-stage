import { ModelInfo } from './viewer-types';

/** A count with thousands separators, so 12345 reads as 12,345. */
export function formatCount(n: number): string {
  return n.toLocaleString('en-US');
}

/** A length in metres to a sensible precision: 1.2 m, 0.35 m, 12 m. */
export function formatMetres(m: number): string {
  const digits = m >= 10 ? 0 : m >= 1 ? 1 : 2;
  return `${m.toFixed(digits)} m`;
}

/** The one-line summary under the viewer. */
export function statsLine(info: ModelInfo): string {
  const [x, y, z] = info.size;
  const materials = info.materials.length === 1 ? '1 material' : `${info.materials.length} materials`;
  return `${formatCount(info.triangles)} triangles, ${formatCount(info.vertices)} vertices, ${formatMetres(x)} × ${formatMetres(y)} × ${formatMetres(z)}, ${materials}`;
}

/** Seconds as 0.00 for the clip clock. */
export function formatSeconds(s: number): string {
  return s.toFixed(2);
}

export const SPEEDS = [0.25, 0.5, 1, 2] as const;
