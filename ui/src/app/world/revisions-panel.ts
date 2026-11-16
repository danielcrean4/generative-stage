import { Component, effect, inject, input, output, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { firstValueFrom } from 'rxjs';
import { toWorldError, WorldApi } from './world-api';
import { formatTime } from './world-format';
import { Revision } from './world-models';

/** Every word in this panel. */
const WORDS = {
  title: 'Revisions',
  help: 'Every save makes a new revision. Look at an old one, or revert to it; reverting adds a new revision and loses nothing.',
  loading: 'Loading…',
  current: 'Current',
  revision: (n: number) => `Revision ${n}`,
  noNote: 'No note',
  archivedMark: 'archived',
  view: 'View',
  viewing: 'Viewing',
  revert: 'Revert to this',
};

@Component({
  selector: 'app-revisions-panel',
  imports: [MatButtonModule],
  styleUrl: './world-pages.scss',
  template: `
    <section class="side-panel" data-panel="revisions">
      <h3>{{ w.title }}</h3>
      <p class="hint">{{ w.help }}</p>
      @if (error()) {
        <p class="error" role="alert">{{ error() }}</p>
      }
      @if (revisions() === null) {
        <p class="muted">{{ w.loading }}</p>
      } @else {
        <ol class="revs">
          @for (r of revisions(); track r.revision) {
            <li class="rev" [class.is-open]="viewing() === r.revision" [attr.data-revision]="r.revision">
              <div>
                <strong>{{ w.revision(r.revision) }}</strong>
                @if (r.revision === current()) {
                  <span class="badge">{{ w.current }}</span>
                }
                @if (r.archived) {
                  <span class="muted">{{ w.archivedMark }}</span>
                }
                <div class="muted">{{ when(r) }}</div>
                <div class="muted note">{{ r.note || w.noNote }}</div>
              </div>
              <div class="rev-actions">
                <button mat-button (click)="view.emit(r)" [disabled]="viewing() === r.revision">
                  {{ viewing() === r.revision ? w.viewing : w.view }}
                </button>
                @if (r.revision !== current() && !locked()) {
                  <button mat-button (click)="revert.emit(r)">{{ w.revert }}</button>
                }
              </div>
            </li>
          }
        </ol>
      }
    </section>
  `,
  styles: `
    .revs { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.4rem; }
    .rev { display: flex; justify-content: space-between; gap: 0.5rem; padding: 0.4rem 0.6rem; border: 1px solid var(--mat-sys-outline-variant); border-radius: 8px; }
    .rev.is-open { border-color: var(--mat-sys-primary); }
    .rev-actions { display: flex; flex-direction: column; align-items: flex-end; }
    .note { font-size: 0.85rem; }
    .badge { margin-left: 0.4rem; }
  `,
})
export class RevisionsPanel {
  readonly w = WORDS;
  private readonly api = inject(WorldApi);

  readonly slug = input.required<string>();
  readonly entityId = input.required<string>();
  /** The entity's current revision: the list is read again whenever it changes. */
  readonly current = input.required<number>();
  /** The revision being looked at, if any. */
  readonly viewing = input<number | null>(null);
  /** Archived entities are read-only, so reverting is not offered. */
  readonly locked = input(false);
  readonly view = output<Revision>();
  readonly revert = output<Revision>();

  readonly revisions = signal<Revision[] | null>(null);
  readonly error = signal<string | null>(null);

  constructor() {
    effect(() => {
      const slug = this.slug();
      const id = this.entityId();
      this.current();
      void this.load(slug, id);
    });
  }

  when(r: Revision): string {
    return formatTime(r.created_at);
  }

  private async load(slug: string, id: string): Promise<void> {
    this.error.set(null);
    try {
      this.revisions.set(await firstValueFrom(this.api.revisions(slug, id)));
    } catch (err) {
      this.error.set(toWorldError(err).message);
    }
  }
}
