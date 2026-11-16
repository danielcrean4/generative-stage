/**
 * Steps that need the real DOM, after the rendered HTML has been sanitised and inserted.
 * Angular's sanitiser strips `id` attributes, so heading ids are set here.
 */

export interface OutlineEntry {
  id: string;
  text: string;
  /** Level in the doc as written (1 = the doc's own title). */
  level: number;
  /** Source line of the heading. */
  line: number | null;
}

export interface DecoratedDoc {
  outline: OutlineEntry[];
  headingsById: Map<string, HTMLElement>;
}

/** GitHub-style heading slug: lower case, punctuation dropped, spaces become hyphens. */
export function headingSlug(text: string): string {
  return text
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s_-]/gu, '')
    .replace(/\s/g, '-');
}

function sourceLine(el: Element): number | null {
  for (const c of Array.from(el.classList)) {
    const m = /^ln-(\d+)$/.exec(c);
    if (m) return Number(m[1]);
  }
  return null;
}

/** Gives every heading a stable id (duplicates get -1, -2 ...) and lists them for the outline. */
export function decorateDoc(root: HTMLElement): DecoratedDoc {
  const used = new Map<string, number>();
  const outline: OutlineEntry[] = [];
  const headingsById = new Map<string, HTMLElement>();
  root.querySelectorAll<HTMLElement>('h2, h3, h4, h5, h6').forEach((h) => {
    const text = (h.textContent ?? '').trim();
    const base = headingSlug(text) || 'section';
    const seen = used.get(base) ?? 0;
    used.set(base, seen + 1);
    const id = seen === 0 ? base : `${base}-${seen}`;
    h.id = id;
    headingsById.set(id, h);
    outline.push({ id, text, level: Number(h.tagName.slice(1)) - 1, line: sourceLine(h) });
  });
  return { outline, headingsById };
}

/** The heading an anchor names, tolerating percent-encoding and case. */
export function findAnchor(doc: DecoratedDoc, anchor: string): HTMLElement | null {
  const tries = [anchor];
  try {
    tries.push(decodeURIComponent(anchor));
  } catch {
    /* keep the raw form only */
  }
  for (const t of [...tries, ...tries.map((x) => x.toLowerCase())]) {
    const el = doc.headingsById.get(t);
    if (el) return el;
  }
  return null;
}

/** The last top-level block that starts on or before the given source line. */
export function findLine(root: HTMLElement, line: number): HTMLElement | null {
  let best: HTMLElement | null = null;
  let bestLine = 0;
  for (const child of Array.from(root.children) as HTMLElement[]) {
    const n = sourceLine(child);
    if (n !== null && n <= line && n >= bestLine) {
      best = child;
      bestLine = n;
    }
  }
  return best;
}
