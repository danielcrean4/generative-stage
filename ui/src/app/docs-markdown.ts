import MarkdownIt, { type Env as MdEnv, type Token } from 'markdown-it';
import type { DocLink } from './docs-view-api';
import { docFileHref, sourceHref } from './docs-links';

/**
 * Markdown to HTML for the docs view.
 *
 * Safety: raw HTML in a doc is never parsed as HTML (`html: false`, so a `<script>` is shown as
 * text), markdown-it's own link check refuses `javascript:`, `vbscript:`, `file:` and `data:`
 * links, images are never loaded (a placeholder is shown), and the caller also runs the result
 * through Angular's sanitiser before it reaches the page.
 *
 * Every link becomes one of: `doc-link` / `src-link` (a Studio URL the component routes),
 * `anchor-link` (`#heading`), `ext-link` (new tab, noopener), or plain text with a small mark.
 * Top-level blocks carry a class `ln-<source line>` so the page can scroll to a search hit.
 * Headings are demoted by one level because the page has its own h1.
 */

export const SOURCE_BLOCKED_NOTE =
  'not shown: outside the folders this project lets the docs view open';

interface Env extends MdEnv {
  project: string;
  linkMap: Map<string, DocLink>;
  closers: string[];
}

const md = new MarkdownIt({ html: false, linkify: false, typographer: false });
const esc = md.utils.escapeHtml;

function lookup(env: Env, href: string): DocLink | undefined {
  const hit = env.linkMap.get(href);
  if (hit) return hit;
  try {
    return env.linkMap.get(decodeURI(href));
  } catch {
    return undefined;
  }
}

/** `[ ] ` and `[x] ` at the start of a list item become a box. */
const TASK = /^\[( |x|X)\] /;

md.core.ruler.push('studio_blocks', (state) => {
  const tokens = state.tokens;
  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i];
    if (
      t.level === 0 &&
      t.map &&
      (t.nesting === 1 || t.type === 'fence' || t.type === 'hr' || t.type === 'code_block')
    ) {
      t.attrJoin('class', `ln-${t.map[0] + 1}`);
    }
    if (t.type === 'heading_open') {
      const level = Math.min(6, Number(t.tag.slice(1)) + 1);
      t.tag = `h${level}`;
      const close = tokens.slice(i).find((x) => x.type === 'heading_close');
      if (close) close.tag = t.tag;
    }
    if (t.type === 'list_item_open') {
      const inline = tokens[i + 2];
      if (tokens[i + 1]?.type === 'paragraph_open' && inline?.type === 'inline') {
        const m = TASK.exec(inline.content);
        const first = inline.children?.[0];
        if (m && first && first.type === 'text' && TASK.test(first.content)) {
          const done = m[1] !== ' ';
          first.content = first.content.slice(4);
          inline.content = inline.content.slice(4);
          const box = new state.Token('html_inline', '', 0);
          box.content = `<span class="task-box" role="img" aria-label="${done ? 'done' : 'not done'}">${done ? '☑' : '☐'}</span> `;
          inline.children!.unshift(box);
          t.attrJoin('class', done ? 'task-item task-done' : 'task-item');
        }
      }
    }
  }
});

md.renderer.rules['link_open'] = (tokens: Token[], idx: number, _o, rawEnv) => {
  const env = rawEnv as Env;
  const href = String(tokens[idx].attrGet('href') ?? '');
  const link = lookup(env, href);
  const kind =
    link?.kind ??
    (href.startsWith('#')
      ? 'anchor'
      : /^(https?:|mailto:)/i.test(href)
        ? 'external'
        : 'unresolved');
  switch (kind) {
    case 'anchor':
      env.closers.push('</a>');
      return `<a class="anchor-link" href="${esc(href)}">`;
    case 'external':
      env.closers.push('</a>');
      return `<a class="ext-link" href="${esc(link?.url ?? href)}" target="_blank" rel="noopener noreferrer">`;
    case 'doc':
      if (link?.path && link.exists) {
        env.closers.push('</a>');
        return `<a class="doc-link" href="${esc(docFileHref(env.project, link.path, { anchor: link.anchor }))}">`;
      }
      env.closers.push('</span> <small class="link-mark">missing</small>');
      return `<span class="link-missing" title="This doc does not exist in the project.">`;
    case 'source':
      if (link?.path && link.allowed && link.exists === false) {
        env.closers.push('</span> <small class="link-mark">missing</small>');
        return `<span class="link-missing" title="This file does not exist in the project.">`;
      }
      env.closers.push('</a>');
      return `<a class="src-link${link?.allowed ? '' : ' src-blocked'}" href="${esc(
        sourceHref(env.project, link?.path ?? href, { line: link?.line, blocked: !link?.allowed }),
      )}"${link?.allowed ? '' : ` title="${esc(SOURCE_BLOCKED_NOTE)}"`}>`;
    default:
      env.closers.push('</span> <small class="link-mark">not linked</small>');
      return `<span class="link-plain" title="This link points somewhere the docs view does not open.">`;
  }
};

md.renderer.rules['link_close'] = (_t, _i, _o, env) => (env as Env).closers.pop() ?? '</a>';

// Images are never fetched: the server has no route for repo images, and external ones would
// make the page depend on the network.
md.renderer.rules['image'] = (tokens, idx, _o, env, slf) =>
  `<span class="doc-image" title="Images are not shown in the docs view.">[image: ${esc(
    slf.renderInlineAsText(tokens[idx].children ?? [], _o, env) || 'no description',
  )}]</span>`;

md.renderer.rules['fence'] = (tokens, idx, _o, _env, slf) => {
  const t = tokens[idx];
  const lang = t.info.trim().split(/\s+/)[0];
  const cls = lang ? ` class="language-${esc(lang)}"` : '';
  return `<pre${slf.renderAttrs(t)} tabindex="0"><code${cls}>${esc(t.content)}</code></pre>\n`;
};

// Wide tables scroll sideways inside a focusable region instead of stretching the page.
md.renderer.rules['table_open'] = (tokens, idx, _o, _e, slf) =>
  `<div${slf.renderAttrs(tokens[idx])} role="region" aria-label="Table" tabindex="0"><table>\n`;
md.renderer.rules['table_close'] = () => '</table></div>\n';

/** Renders a doc to an HTML string. The result still has to be sanitised by the caller. */
export function renderMarkdown(text: string, project: string, links: DocLink[]): string {
  const linkMap = new Map<string, DocLink>();
  for (const l of links) if (!linkMap.has(l.target)) linkMap.set(l.target, l);
  const env: Env = { project, linkMap, closers: [] };
  return md.render(text, env);
}
