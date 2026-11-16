import { Component, ElementRef, computed, input, signal, viewChild } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { NotesData } from './notes-data';
import { EntityRef, imageProblem, insertMention, matchEntities, mentionTrigger, toStoredText } from './notes-model';

/** Every word in the composer. */
const WORDS = {
  placeholder: 'Add a note…',
  label: 'Add a note',
  hint: 'Enter posts, Shift+Enter starts a new line. Type @ to mention something. Paste or drop an image to attach it.',
  post: 'Post',
  posting: 'Posting…',
  addImage: 'Add image',
  removeImage: (name: string) => `Remove ${name}`,
  mentions: 'Mention an entity',
  draftImage: (name: string) => `Attached: ${name}`,
};

interface Draft {
  file: File;
  url: string;
}

/**
 * The always-visible box for writing a note. Enter posts, Shift+Enter starts a line. Pasted or
 * dropped images wait under the box until posted. Typing `@` offers the project's entities.
 */
@Component({
  selector: 'app-profile-composer',
  imports: [MatButtonModule],
  styles: `
    :host { display: block; min-width: 0; }
    .box { position: relative; }
    textarea { font: inherit; width: 100%; box-sizing: border-box; min-height: 3.2rem; padding: 0.5rem 0.65rem; border: 1px solid var(--mat-sys-outline); border-radius: 8px; background: var(--mat-sys-surface); color: inherit; resize: vertical; display: block; }
    textarea:focus { outline: 2px solid var(--mat-sys-primary); outline-offset: -1px; }
    .over textarea { border-color: var(--mat-sys-primary); background: var(--mat-sys-primary-container); }
    .menu { position: absolute; left: 0.5rem; right: 0.5rem; top: 100%; z-index: 5; margin: 0.15rem 0 0; padding: 0.25rem; list-style: none; background: var(--mat-sys-surface-container-highest); border: 1px solid var(--mat-sys-outline-variant); border-radius: 8px; box-shadow: 0 4px 14px rgb(0 0 0 / 0.2); max-height: 14rem; overflow-y: auto; }
    .menu li { padding: 0.3rem 0.5rem; border-radius: 6px; cursor: pointer; overflow-wrap: anywhere; }
    .menu li[aria-selected='true'], .menu li:hover { background: var(--mat-sys-primary-container); color: var(--mat-sys-on-primary-container); }
    .menu .kind { font-size: 0.75rem; color: var(--mat-sys-on-surface-variant); margin-left: 0.4rem; }
    .drafts { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.4rem; }
    .draft { position: relative; }
    .draft img { display: block; width: 4.5rem; height: 4.5rem; object-fit: cover; border-radius: 8px; border: 1px solid var(--mat-sys-outline-variant); }
    .draft button { position: absolute; top: -6px; right: -6px; width: 1.4rem; height: 1.4rem; border-radius: 50%; border: 0; cursor: pointer; background: var(--mat-sys-inverse-surface); color: var(--mat-sys-inverse-on-surface); line-height: 1; padding: 0; }
    .row { display: flex; align-items: center; gap: 0.5rem; margin-top: 0.4rem; flex-wrap: wrap; }
    .hint { flex: 1 1 14rem; min-width: 0; font-size: 0.8rem; color: var(--mat-sys-on-surface-variant); margin: 0; }
    .error { color: var(--mat-sys-error); font-size: 0.85rem; margin: 0.3rem 0 0; }
    input[type='file'] { display: none; }
  `,
  template: `
    <section data-panel="composer">
      <div class="box" [class.over]="over()">
        <textarea
          #box
          rows="2"
          [placeholder]="w.placeholder"
          [attr.aria-label]="w.label"
          [value]="text()"
          (input)="typed()"
          (keydown)="key($event)"
          (keyup)="look()"
          (click)="look()"
          (paste)="paste($event)"
          (dragover)="dragOver($event)"
          (dragleave)="over.set(false)"
          (drop)="drop($event)"
          data-testid="composer"
        ></textarea>
        @if (offers().length) {
          <ul class="menu" role="listbox" [attr.aria-label]="w.mentions" data-testid="mention-menu">
            @for (e of offers(); track e.id; let i = $index) {
              <li role="option" [attr.aria-selected]="i === active()" [attr.data-mention-option]="e.id" (mousedown)="$event.preventDefault(); pick(e)">{{ e.title }}<span class="kind">{{ e.kind }}</span></li>
            }
          </ul>
        }
      </div>
      @if (drafts().length) {
        <div class="drafts" data-testid="composer-drafts">
          @for (d of drafts(); track d.url) {
            <span class="draft"><img [src]="d.url" [alt]="w.draftImage(d.file.name)" /><button type="button" [attr.aria-label]="w.removeImage(d.file.name)" (click)="removeDraft(d)">×</button></span>
          }
        </div>
      }
      <div class="row">
        <p class="hint">{{ w.hint }}</p>
        <button mat-stroked-button type="button" (click)="files.click()" data-action="add-image">{{ w.addImage }}</button>
        <input #files type="file" accept="image/png,image/jpeg,image/webp" multiple (change)="chosen(files)" data-testid="composer-file" />
        <button mat-flat-button type="button" (click)="post()" [disabled]="busy() || !canPost()" data-action="post-note">{{ busy() ? w.posting : w.post }}</button>
      </div>
      @if (problem(); as message) {
        <p class="error" role="alert">{{ message }}</p>
      }
    </section>
  `,
})
export class ProfileComposer {
  readonly w = WORDS;
  readonly data = input.required<NotesData>();
  readonly text = signal('');
  readonly drafts = signal<Draft[]>([]);
  readonly busy = signal(false);
  readonly over = signal(false);
  readonly problem = signal<string | null>(null);
  readonly active = signal(0);
  private readonly caret = signal(0);
  private picked: EntityRef[] = [];
  private readonly box = viewChild.required<ElementRef<HTMLTextAreaElement>>('box');

  private readonly dismissed = signal(false);
  private readonly trigger = computed(() => (this.dismissed() ? null : mentionTrigger(this.text(), this.caret())));
  /** The entities to offer while an `@word` is being typed (not this entity itself). */
  readonly offers = computed(() => {
    const t = this.trigger();
    return t ? matchEntities(this.data().entities().filter((e) => e.id !== this.data().entityId), t.query) : [];
  });
  readonly canPost = computed(() => this.text().trim().length > 0 || this.drafts().length > 0);

  /** The text box changed. */
  typed(): void {
    this.text.set(this.box().nativeElement.value);
    this.dismissed.set(false);
    this.look();
  }

  /** Read where the caret is, to know whether an `@word` is being typed. */
  look(): void {
    this.caret.set(this.box().nativeElement.selectionStart);
    this.active.set(0);
  }

  key(event: KeyboardEvent): void {
    const offers = this.offers();
    if (offers.length) {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const step = event.key === 'ArrowDown' ? 1 : offers.length - 1;
        this.active.set((this.active() + step) % offers.length);
        return;
      }
      if (event.key === 'Enter' || event.key === 'Tab') {
        event.preventDefault();
        this.pick(offers[this.active()] ?? offers[0]);
        return;
      }
      if (event.key === 'Escape') {
        event.preventDefault();
        this.dismissed.set(true);
        return;
      }
    }
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      void this.post();
    }
  }

  pick(entity: EntityRef): void {
    const trigger = this.trigger();
    if (!trigger) return;
    const box = this.box().nativeElement;
    const next = insertMention(this.text(), trigger, box.selectionStart, entity.title);
    if (!this.picked.includes(entity)) this.picked.push(entity);
    this.text.set(next.text);
    box.value = next.text;
    box.setSelectionRange(next.caret, next.caret);
    box.focus();
    this.caret.set(next.caret);
  }

  paste(event: ClipboardEvent): void {
    const images = [...(event.clipboardData?.files ?? [])].filter((f) => f.type.startsWith('image/'));
    if (images.length) {
      event.preventDefault();
      this.addImages(images);
    }
  }

  dragOver(event: DragEvent): void {
    if (event.dataTransfer?.types.includes('Files')) {
      event.preventDefault();
      this.over.set(true);
    }
  }

  drop(event: DragEvent): void {
    this.over.set(false);
    const images = [...(event.dataTransfer?.files ?? [])];
    if (images.length) {
      event.preventDefault();
      this.addImages(images);
    }
  }

  chosen(input: HTMLInputElement): void {
    this.addImages([...(input.files ?? [])]);
    input.value = '';
  }

  private addImages(files: File[]): void {
    this.problem.set(null);
    for (const file of files) {
      const why = imageProblem(file);
      if (why) this.problem.set(why);
      else this.drafts.update((d) => [...d, { file, url: URL.createObjectURL(file) }]);
    }
  }

  removeDraft(draft: Draft): void {
    URL.revokeObjectURL(draft.url);
    this.drafts.update((d) => d.filter((x) => x !== draft));
  }

  async post(): Promise<void> {
    if (this.busy() || !this.canPost()) return;
    this.busy.set(true);
    this.problem.set(null);
    const stored = toStoredText(this.text(), this.picked);
    const problem = await this.data().post(stored, this.drafts().map((d) => d.file));
    this.busy.set(false);
    if (problem) {
      this.problem.set(problem);
      return;
    }
    this.drafts().forEach((d) => URL.revokeObjectURL(d.url));
    this.drafts.set([]);
    this.picked = [];
    this.text.set('');
    this.box().nativeElement.value = '';
    this.caret.set(0);
  }
}

