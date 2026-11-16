import { legend, linkPath, segments } from './prompt-parts';
import { PromptPart } from './world-models';

const style = { type: 'style' as const, id: 'prop.clay', changed: false };
const parts: PromptPart[] = [
  { text: 'a brass key', start: 0, end: 11, source: { kind: 'subject', id: 'job1', link: { type: 'entity', id: 'e1', kind: 'prop' } } },
  { text: ' made of ', start: 11, end: 20, source: { kind: 'style_pack', id: 'clay', key: 'prompt.templates.prop', version: 2, link: style } },
  { text: 'repair-shop parts', start: 20, end: 37, source: { kind: 'motif', id: 'repair_shop', link: { type: 'motif', id: 'prop.repair_shop' } } },
  { text: ', hand-sculpted', start: 37, end: 52, source: { kind: 'style_pack', id: 'clay', key: 'prompt.templates.prop', link: style } },
  { text: ', ', start: 52, end: 54, source: { kind: 'glue', link: null } },
  { text: 'plain white background', start: 54, end: 76, source: { kind: 'pipeline', id: 'prop', key: 'capture.background.words', link: null } },
];

describe('prompt parts', () => {
  it('names each piece by tone and label, with a sentence for where it came from', () => {
    const found = segments(parts, 'Key');
    expect(found.map((s) => [s.tone, s.label])).toEqual([
      ['subject', 'Description'],
      ['style', 'Style'],
      ['motif', 'Motif'],
      ['style', 'Style'],
      ['glue', ''],
      ['capture', 'Capture'],
    ]);
    expect(found[0].detail).toBe('The description this run started from, for Key.');
    expect(found[1].detail).toBe('The style pack "clay", version 2, prompt.templates.prop.');
    expect(found[5].detail).toBe('The capture words of the "prop" pipeline file, capture.background.words.');
    expect(found.map((s) => s.text).join('')).toBe(parts.map((p) => p.text).join(''));
  });

  it('lists each source once with its share of the words, joining commas left out', () => {
    const entries = legend(segments(parts));
    expect(entries.map((e) => e.label)).toEqual(['Description', 'Style', 'Motif', 'Capture']);
    expect(entries.map((e) => e.share)).toEqual([15, 32, 23, 30]);
    expect(entries.reduce((sum, e) => sum + e.share, 0)).toBe(100);
    expect(entries[1].detail).toBe('The style pack "clay", version 2.');
    expect(entries[1].link).toEqual(style);
  });

  it('routes a source link to its page and a record link to its profile', () => {
    expect(linkPath(style)).toEqual(['/sources', 'style', 'prop.clay']);
    expect(linkPath({ type: 'entity', id: 'e1', kind: 'prop' })).toEqual(['/world', 'prop', 'e1']);
  });
});
