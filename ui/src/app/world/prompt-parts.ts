import { PartLink, PromptPart } from './world-models';

/**
 * The rules behind the coloured prompt, with no drawing in them: what each piece of a prompt is called, which colour group it
 * belongs to, a sentence saying where it came from, and how much of the prompt each source supplied.
 */

export type Tone = 'style' | 'motif' | 'subject' | 'capture' | 'glue';

export interface Segment {
  index: number;
  text: string;
  tone: Tone;
  /** The short word shown on the piece, as well as its colour. */
  label: string;
  /** Pieces of the same source share a group. */
  group: string;
  /** A sentence: where this piece came from. */
  detail: string;
  link: PartLink | null;
}

export interface LegendEntry {
  group: string;
  tone: Tone;
  label: string;
  detail: string;
  /** Whole percent of the prompt's words (not its joining commas) this source supplied. */
  share: number;
  link: PartLink | null;
}

const TONES: Record<string, Tone> = { style_pack: 'style', motif: 'motif', subject: 'subject', pipeline: 'capture' };
const LABELS: Record<Tone, string> = { style: 'Style', motif: 'Motif', subject: 'Description', capture: 'Capture', glue: '' };

function detailOf(part: PromptPart, title: string | null): string {
  const { kind, id, key, version } = part.source;
  switch (kind) {
    case 'style_pack':
      return `The style pack "${id}"${version ? `, version ${version}` : ''}${key ? `, ${key}` : ''}.`;
    case 'motif':
      return `The motif "${id}".`;
    case 'subject':
      return title ? `The description this run started from, for ${title}.` : 'The description this run started from.';
    case 'pipeline':
      return `The capture words of the "${id}" pipeline file${key ? `, ${key}` : ''}.`;
    default:
      return 'Joins the pieces.';
  }
}

/** The pieces of a prompt as drawable segments, in order. */
export function segments(parts: PromptPart[], title: string | null = null): Segment[] {
  return parts.map((part, index) => {
    const tone = part.source.kind === 'glue' ? 'glue' : (TONES[part.source.kind] ?? 'capture');
    return {
      index,
      text: part.text,
      tone,
      label: tone === 'glue' ? '' : LABELS[tone],
      group: tone === 'glue' ? 'glue' : `${part.source.kind}:${part.source.id ?? ''}`,
      detail: detailOf(part, title),
      link: part.source.link,
    };
  });
}

/** One entry per source, in the order it first appears, with the share of the prompt's words it supplied. */
export function legend(parts: Segment[]): LegendEntry[] {
  const words = parts.filter((p) => p.tone !== 'glue');
  const total = words.reduce((sum, p) => sum + p.text.length, 0);
  const found = new Map<string, { first: Segment; chars: number }>();
  for (const p of words) {
    const entry = found.get(p.group);
    if (entry) entry.chars += p.text.length;
    else found.set(p.group, { first: p, chars: p.text.length });
  }
  return [...found.values()].map(({ first, chars }) => ({
    group: first.group,
    tone: first.tone,
    label: first.label,
    detail: first.detail.replace(/, (prompt|capture)\.[\w.]+\.?$/, '.'),
    share: total ? Math.round((chars / total) * 100) : 0,
    link: first.link,
  }));
}

/** The router path of a source page, or of the profile for the description. */
export function linkPath(link: PartLink): string[] {
  return link.type === 'entity' ? ['/world', link.kind ?? '', link.id] : ['/sources', link.type, link.id];
}

const TYPE_WORDS: Record<string, string> = { style: 'style pack', motif: 'motif', contract: 'contract', entity: 'record', pipeline: 'pipeline file' };

export function typeWord(type: string): string {
  return TYPE_WORDS[type] ?? type;
}
