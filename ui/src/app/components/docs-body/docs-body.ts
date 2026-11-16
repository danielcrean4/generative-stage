import {
  Component,
  ElementRef,
  SecurityContext,
  ViewEncapsulation,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { DomSanitizer } from '@angular/platform-browser';
import { Router } from '@angular/router';
import { DocLink } from '../../docs-view-api';
import { DecoratedDoc, OutlineEntry, decorateDoc, findAnchor, findLine } from '../../docs-dom';
import { renderMarkdown } from '../../docs-markdown';

/**
 * One rendered markdown doc. Owns turning text into safe HTML (markdown-it with raw HTML off,
 * then Angular's sanitiser), the links inside it, and scrolling to an anchor or a source line.
 */
@Component({
  selector: 'app-docs-body',
  template: '',
  styleUrl: './docs-body.scss',
  encapsulation: ViewEncapsulation.None,
  host: { class: 'doc-body', '(click)': 'onClick($event)' },
})
export class DocsBody {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef).nativeElement;
  private readonly sanitizer = inject(DomSanitizer);
  private readonly router = inject(Router);

  readonly project = input.required<string>();
  readonly text = input.required<string>();
  readonly links = input<DocLink[]>([]);
  /** A heading to scroll to (from the URL's `#fragment`). */
  readonly fragment = input<string | null>(null);
  /** A source line to scroll to (a search hit). */
  readonly line = input<number | null>(null);

  /** The doc's headings, once rendered. */
  readonly outline = output<OutlineEntry[]>();

  private readonly decorated = signal<DecoratedDoc | null>(null);

  private readonly html = computed(() => renderMarkdown(this.text(), this.project(), this.links()));

  constructor() {
    effect(() => {
      const safe = this.sanitizer.sanitize(SecurityContext.HTML, this.html()) ?? '';
      this.host.innerHTML = safe;
      const doc = decorateDoc(this.host);
      this.decorated.set(doc);
      this.outline.emit(doc.outline);
    });
    effect(() => {
      const doc = this.decorated();
      const fragment = this.fragment();
      const line = this.line();
      if (!doc) return;
      this.scrollToTarget(doc, fragment, line);
    });
  }

  onClick(event: MouseEvent): void {
    const a = (event.target as Element).closest('a');
    if (!a || !this.host.contains(a) || event.button !== 0) return;
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const href = a.getAttribute('href') ?? '';
    if (a.classList.contains('anchor-link')) {
      event.preventDefault();
      this.goToAnchor(href.slice(1));
    } else if (a.classList.contains('doc-link') || a.classList.contains('src-link')) {
      event.preventDefault();
      void this.router.navigateByUrl(href);
    }
    // External links keep their own href, target="_blank" and rel="noopener noreferrer".
  }

  /** Scrolls to a heading and puts it in the URL so the position can be linked. */
  goToAnchor(fragment: string): void {
    const doc = this.decorated();
    const el = doc ? findAnchor(doc, fragment) : null;
    if (el) this.reveal(el);
    void this.router.navigate([], { queryParamsHandling: 'preserve', fragment });
  }

  private scrollToTarget(doc: DecoratedDoc, fragment: string | null, line: number | null): void {
    let el: HTMLElement | null = null;
    if (fragment) el = findAnchor(doc, fragment);
    if (!el && line) el = findLine(this.host, line);
    if (el) this.reveal(el);
  }

  private reveal(el: HTMLElement): void {
    this.host
      .querySelectorAll('.scroll-target')
      .forEach((x) => x.classList.remove('scroll-target'));
    el.classList.add('scroll-target');
    el.tabIndex = -1;
    el.scrollIntoView?.({ block: 'start' });
    el.focus({ preventScroll: true });
  }
}
