import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { DocLink } from '../../docs-view-api';
import { OutlineEntry } from '../../docs-dom';
import { link } from '../../docs-view.fixtures';
import { DocsBody } from './docs-body';

async function render(
  text: string,
  links: DocLink[] = [],
  inputs: { fragment?: string | null; line?: number | null } = {},
) {
  TestBed.configureTestingModule({ imports: [DocsBody], providers: [provideRouter([])] });
  const fixture = TestBed.createComponent(DocsBody);
  const outlines: OutlineEntry[][] = [];
  fixture.componentInstance.outline.subscribe((o) => outlines.push(o));
  fixture.componentRef.setInput('project', 'my-game');
  fixture.componentRef.setInput('text', text);
  fixture.componentRef.setInput('links', links);
  if (inputs.fragment !== undefined) fixture.componentRef.setInput('fragment', inputs.fragment);
  if (inputs.line !== undefined) fixture.componentRef.setInput('line', inputs.line);
  await fixture.whenStable();
  fixture.detectChanges();
  await fixture.whenStable();
  return { fixture, el: fixture.nativeElement as HTMLElement, outlines };
}

describe('DocsBody rendering', () => {
  it('renders a table inside a scrollable region, with header cells', async () => {
    const { el } = await render('| Gate | Result |\n|---|---|\n| mesh | pass |\n');
    const region = el.querySelector('[role="region"]');
    expect(region?.getAttribute('tabindex')).toBe('0');
    expect(region?.querySelectorAll('th').length).toBe(2);
    expect(region?.querySelector('td')?.textContent).toBe('mesh');
  });

  it('renders fenced code as a focusable pre/code block with its language', async () => {
    const { el } = await render('```python\nprint("hi <b>")\n```\n');
    const pre = el.querySelector('pre');
    expect(pre?.getAttribute('tabindex')).toBe('0');
    expect(pre?.querySelector('code.language-python')?.textContent).toContain('print("hi <b>")');
    expect(pre?.querySelector('b')).toBeNull();
  });

  it('gives headings stable GitHub-style ids, numbers duplicates, and demotes them under the page h1', async () => {
    const { el, outlines } = await render(
      '# Title\n\n## Same name\n\n## Same name\n\n### Rules & Notes!\n',
    );
    expect(el.querySelector('h1')).toBeNull();
    const ids = Array.from(el.querySelectorAll('h2, h3, h4')).map((h) => `${h.tagName}:${h.id}`);
    expect(ids).toEqual(['H2:title', 'H3:same-name', 'H3:same-name-1', 'H4:rules--notes']);
    const last = outlines[outlines.length - 1];
    expect(last.map((o) => [o.level, o.id])).toEqual([
      [1, 'title'],
      [2, 'same-name'],
      [2, 'same-name-1'],
      [3, 'rules--notes'],
    ]);
    expect(last[0].line).toBe(1);
  });

  it('renders task lists and nested lists', async () => {
    const { el } = await render('- [x] done\n- [ ] todo\n  - nested one\n    - deeper\n');
    const items = el.querySelectorAll('li.task-item');
    expect(items.length).toBe(2);
    expect(items[0].querySelector('.task-box')?.getAttribute('aria-label')).toBe('done');
    expect(items[1].querySelector('.task-box')?.getAttribute('aria-label')).toBe('not done');
    expect(items[0].textContent).not.toContain('[x]');
    expect(el.querySelectorAll('ul ul ul').length).toBe(1);
  });

  it('never loads an image: it shows its description instead', async () => {
    const { el } = await render('![a diagram](pics/x.png) ![](https://example.com/t.gif)');
    expect(el.querySelector('img')).toBeNull();
    expect(el.querySelector('.doc-image')?.textContent).toBe('[image: a diagram]');
  });
});

describe('DocsBody safety', () => {
  const hostile = [
    '# Hostile doc',
    '',
    '<script>window.__pwned = 1</script>',
    '',
    '<img src=x onerror="window.__pwned = 2">',
    '',
    '[click me](javascript:window.__pwned=3)',
    '',
    '[encoded](&#106;avascript:window.__pwned=4)',
    '',
    'Inline <b onclick="window.__pwned=5">bold</b> and <a href="javascript:void(0)">raw anchor</a>.',
    '',
    '<div onmouseover="window.__pwned=6">block html</div>',
    '',
  ].join('\n');

  it('lets no script, event handler or javascript: link survive', async () => {
    const { el } = await render(hostile, [
      link({ target: 'javascript:window.__pwned=3', kind: 'unsupported' }),
    ]);
    expect(el.querySelector('script')).toBeNull();
    expect(el.querySelector('img')).toBeNull();
    expect(el.querySelector('b, div')).toBeNull();
    const withHandler = Array.from(el.querySelectorAll('*')).filter((n) =>
      n.getAttributeNames().some((a) => a.toLowerCase().startsWith('on')),
    );
    expect(withHandler).toEqual([]);
    const hrefs = Array.from(el.querySelectorAll('[href]')).map((a) =>
      a.getAttribute('href')!.toLowerCase(),
    );
    expect(hrefs.filter((h) => h.includes('javascript'))).toEqual([]);
    expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
    // The hostile text is still readable, as text.
    expect(el.textContent).toContain('<script>');
    expect(el.textContent).toContain('click me');
  });

  it('also stays safe when the server wrongly files a javascript: link as a doc or external link', async () => {
    const { el } = await render('[a](javascript:alert(1)) [b](JaVaScRiPt:alert(2))', [
      link({ target: 'javascript:alert(1)', kind: 'external', url: 'javascript:alert(1)' }),
    ]);
    expect(el.innerHTML.toLowerCase()).not.toContain('href="javascript');
    expect(el.querySelector('a')).toBeNull();
  });
});

describe('DocsBody links', () => {
  const links = [
    link({
      target: 'vision.md#power',
      kind: 'doc',
      path: 'docs/vision.md',
      exists: true,
      anchor: 'power',
    }),
    link({ target: 'gone.md', kind: 'doc', path: 'docs/gone.md', exists: false, anchor: null }),
    link({ target: '#details', kind: 'anchor' }),
    link({ target: 'https://example.com/x', kind: 'external', url: 'https://example.com/x' }),
    link({
      target: '../ui/hint.gd:40',
      kind: 'source',
      path: 'ui/hint.gd',
      line: 40,
      allowed: true,
      exists: true,
    }),
    link({
      target: '../secret/key.txt',
      kind: 'source',
      path: 'secret/key.txt',
      line: null,
      allowed: false,
      exists: true,
    }),
    link({
      target: '../ui/lost.gd',
      kind: 'source',
      path: 'ui/lost.gd',
      line: null,
      allowed: true,
      exists: false,
    }),
    link({ target: '../../elsewhere', kind: 'outside' }),
  ];
  const text = [
    '## Details',
    '',
    '[doc](vision.md#power) [gone](gone.md) [here](#details) [ext](https://example.com/x)',
    '[src](../ui/hint.gd:40) [blocked](../secret/key.txt) [lost](../ui/lost.gd) [out](../../elsewhere)',
  ].join('\n');

  it('points an in-project doc link at the docs view, keeping the anchor', async () => {
    const { el } = await render(text, links);
    const a = el.querySelector('a.doc-link')!;
    expect(a.getAttribute('href')).toBe('/docs/my-game/file?path=docs%2Fvision.md#power');
  });

  it('opens a doc link in the docs view through the router, not by reloading', async () => {
    const { el, fixture } = await render(text, links);
    const nav = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    const event = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 });
    el.querySelector('a.doc-link')!.dispatchEvent(event);
    fixture.detectChanges();
    expect(event.defaultPrevented).toBe(true);
    expect(nav).toHaveBeenCalledWith('/docs/my-game/file?path=docs%2Fvision.md#power');
  });

  it('scrolls an anchor link and puts the fragment in the URL', async () => {
    const { el } = await render(text, links);
    const nav = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    const heading = el.querySelector('#details') as HTMLElement;
    heading.scrollIntoView = vi.fn();
    const event = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 });
    el.querySelector('a.anchor-link')!.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    expect(heading.scrollIntoView).toHaveBeenCalled();
    expect(nav).toHaveBeenCalledWith([], { queryParamsHandling: 'preserve', fragment: 'details' });
  });

  it('opens an external link in a new tab with rel=noopener and leaves the click alone', async () => {
    const { el } = await render(text, links);
    const nav = vi.spyOn(TestBed.inject(Router), 'navigateByUrl');
    const a = el.querySelector('a.ext-link')!;
    expect(a.getAttribute('target')).toBe('_blank');
    expect(a.getAttribute('rel')).toContain('noopener');
    expect(a.getAttribute('href')).toBe('https://example.com/x');
    const event = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 });
    a.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
    expect(nav).not.toHaveBeenCalled();
  });

  it('opens an allowed source link in the source pane at its line', async () => {
    const { el } = await render(text, links);
    const a = el.querySelector('a.src-link:not(.src-blocked)')!;
    expect(a.getAttribute('href')).toBe('/docs/my-game/source?path=ui%2Fhint.gd&line=40');
  });

  it('marks a source link outside the allowlist, so the pane can explain instead of failing', async () => {
    const { el } = await render(text, links);
    const a = el.querySelector('a.src-blocked')!;
    expect(a.getAttribute('href')).toBe('/docs/my-game/source?path=secret%2Fkey.txt&blocked=1');
    expect(a.getAttribute('title')).toContain(
      'not shown: outside the folders this project lets the docs view open',
    );
  });

  it('shows a missing doc, a missing source file and an outside link as plain text with a mark', async () => {
    const { el } = await render(text, links);
    const missing = Array.from(el.querySelectorAll('.link-missing')).map((e) => e.textContent);
    expect(missing).toEqual(['gone', 'lost']);
    expect(el.querySelectorAll('.link-mark').length).toBe(3);
    expect(el.textContent).toContain('gone missing');
    expect(el.querySelector('.link-plain')?.textContent).toBe('out');
    expect(el.querySelector('a[href*="gone.md"]')).toBeNull();
  });

  it('scrolls to the heading above a search hit line', async () => {
    const { el } = await render('# A\n\ntext\n\n## B\n\nmore\n\npara at ten\n', [], { line: 10 });
    const target = el.querySelector('.scroll-target');
    expect(target?.textContent).toBe('para at ten');
  });

  it('scrolls to the fragment when one is given', async () => {
    const { el } = await render('## One\n\ntext\n\n## Two\n', [], { fragment: 'two' });
    expect(el.querySelector('.scroll-target')?.id).toBe('two');
  });
});
