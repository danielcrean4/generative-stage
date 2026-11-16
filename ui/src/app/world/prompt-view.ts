import { Component, computed, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { legend, linkPath, Segment, segments, typeWord } from './prompt-parts';
import { PromptPart } from './world-models';

/** Every word in the prompt view. */
const WORDS = {
  legend: 'Where the words came from',
  share: (n: number) => `${n}% of the words`,
  open: (type: string) => `Open the ${type}`,
  changed: 'This file has changed since the run, so the words above may differ from what it holds now.',
  pick: 'Point at or tap a piece of the prompt to see where it came from.',
};

/**
 * A prompt shown as the pieces it was made from, each coloured and labelled by its source, with a legend and, for the piece
 * pointed at or tapped, a card that names its source and links to it. Without recorded pieces (an older run) it shows the plain text.
 */
@Component({
  selector: 'app-prompt-view',
  imports: [RouterLink],
  styleUrl: './prompt-view.scss',
  template: `
    @if (shown().length) {
      <p class="prompt" [attr.data-testid]="testid()">
        @for (s of shown(); track s.index) {
          @if (s.tone === 'glue') {
            <span class="glue">{{ s.text }}</span>
          } @else {
            <button
              type="button"
              class="part"
              [attr.data-tone]="s.tone"
              [attr.data-group]="s.group"
              [class.is-open]="selected() === s.index"
              [attr.aria-expanded]="selected() === s.index"
              (mouseenter)="select(s.index)"
              (focus)="select(s.index)"
              (click)="select(s.index)"
            ><span class="tag">{{ s.label }}</span>{{ s.text }}</button>
          }
        }
      </p>
      <ul class="legend" [attr.aria-label]="w.legend" data-testid="prompt-legend">
        @for (e of entries(); track e.group) {
          <li>
            <span class="swatch" [attr.data-tone]="e.tone"></span>
            <span><strong>{{ e.label }}</strong> {{ e.detail }} <span class="share">{{ w.share(e.share) }}</span></span>
          </li>
        }
      </ul>
      @if (open(); as s) {
        <div class="source-card" data-testid="part-source" [attr.data-tone]="s.tone" role="status">
          <p><strong>{{ s.label || s.group }}</strong> {{ s.detail }}</p>
          @if (s.link; as link) {
            @if (link.changed) {
              <p class="hint">{{ w.changed }}</p>
            }
            <a [routerLink]="path(s)" data-action="open-source">{{ w.open(word(link.type)) }}</a>
          }
        </div>
      } @else {
        <p class="hint">{{ w.pick }}</p>
      }
    } @else if (text()) {
      <pre class="text" [attr.data-testid]="testid()">{{ text() }}</pre>
    }
  `,
})
export class PromptView {
  readonly w = WORDS;
  readonly parts = input<PromptPart[] | null>(null);
  readonly text = input<string | null>(null);
  /** The record the run was made for, named in the description's source sentence. */
  readonly recordTitle = input<string | null>(null);
  readonly testid = input('prompt');

  readonly selected = signal<number | null>(null);
  readonly shown = computed<Segment[]>(() => (this.parts() ? segments(this.parts()!, this.recordTitle()) : []));
  readonly entries = computed(() => legend(this.shown()));
  readonly open = computed(() => this.shown().find((s) => s.index === this.selected()) ?? null);

  select(index: number): void {
    this.selected.set(index);
  }

  path(segment: Segment): string[] {
    return linkPath(segment.link!);
  }

  word = typeWord;
}
