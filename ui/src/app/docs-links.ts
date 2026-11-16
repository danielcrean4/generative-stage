/** The one place that builds the Studio URLs of the docs view (hrefs in rendered docs use them too). */

export function docsHomeHref(project?: string): string {
  return project ? `/docs/${encodeURIComponent(project)}` : '/docs';
}

export function docFileHref(
  project: string,
  path: string,
  opts: { anchor?: string | null; line?: number | null } = {},
): string {
  const q = new URLSearchParams({ path });
  if (opts.line) q.set('line', String(opts.line));
  const hash = opts.anchor ? `#${encodeURIComponent(opts.anchor)}` : '';
  return `/docs/${encodeURIComponent(project)}/file?${q.toString()}${hash}`;
}

/** `blocked` marks a source link the server said is outside the allowlist; the pane then shows a note. */
export function sourceHref(
  project: string,
  path: string,
  opts: { line?: number | null; blocked?: boolean } = {},
): string {
  const q = new URLSearchParams({ path });
  if (opts.line) q.set('line', String(opts.line));
  if (opts.blocked) q.set('blocked', '1');
  return `/docs/${encodeURIComponent(project)}/source?${q.toString()}`;
}
