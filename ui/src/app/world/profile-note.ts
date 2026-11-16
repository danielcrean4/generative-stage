import { Component, ElementRef, computed, inject, input, signal, viewChild } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatMenuModule } from '@angular/material/menu';
import { RouterLink } from '@angular/router';
import { ConfirmService } from './confirm';
import { NotesData } from './notes-data';
import { EntityRef, splitMentions, toDraftText, toStoredText } from './notes-model';
import { formatTime } from './world-format';
import { Note } from './world-models';

/** Every word on a note. */
const WORDS = {
  actions: 'Note actions',
  edit: 'Edit',
  pin: 'Pin',
  unpin: 'Unpin',
  delete: 'Delete',
  save: 'Save',
  cancel: 'Cancel',
  pinned: 'Pinned',
  editLabel: 'Edit the note',
  hint: 'Enter saves, Shift+Enter starts a new line, Escape cancels.',
  unknown: 'an entity',
  image: (name: string) => `Image: ${name}`,
  deleteTitle: 'Delete this note?',
  deleteMessage: 'The note and its images are removed. This cannot be undone.',
};

/** One note: its text with mentions as links, its images, and a menu to edit, pin or delete it. */
@Component({
  selector: 'app-profile-note',
  imports: [RouterLink, MatButtonModule, MatMenuModule],
  styles: `
    :host { display: block; min-width: 0; }
    .head { display: flex; align-items: center; gap: 0.5rem; }
    .meta { font-size: 0.8rem; color: var(--mat-sys-on-surface-variant); flex: 1 1 auto; min-width: 0; }
    .pin { font-size: 0.7rem; padding: 0 0.45rem; border-radius: 999px; background: var(--mat-sys-surface-container-highest); color: var(--mat-sys-on-surface); border: 1px solid var(--mat-sys-outline-variant); margin-left: 0.4rem; }
    .menu { font: inherit; border: 0; background: transparent; color: inherit; cursor: pointer; padding: 0 0.4rem; border-radius: 6px; font-size: 1.1rem; line-height: 1.6; }
    .menu:hover { background: var(--mat-sys-surface-container-high); }
    .text { margin: 0.2rem 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }
    .text a { color: var(--mat-sys-primary); }
    .images { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.4rem; }
    .images img { display: block; max-width: min(14rem, 100%); max-height: 12rem; object-fit: contain; border: 1px solid var(--mat-sys-outline-variant); border-radius: 8px; background: var(--mat-sys-surface-container-low); }
    .edit textarea { font: inherit; width: 100%; box-sizing: border-box; min-height: 4rem; padding: 0.4rem 0.5rem; border: 1px solid var(--mat-sys-primary); border-radius: 6px; background: var(--mat-sys-surface); color: inherit; resize: vertical; }
    .edit .buttons { display: flex; gap: 0.5rem; margin-top: 0.3rem; }
    .hint { font-size: 0.8rem; color: var(--mat-sys-on-surface-variant); margin: 0.2rem 0 0; }
    .error { color: var(--mat-sys-error); font-size: 0.85rem; margin: 0.3rem 0 0; }
  `,
  template: `
    <article [attr.data-note]="note().id">
      <div class="head">
        <span class="meta">{{ when() }} @if (note().pinned) { <span class="pin" data-testid="pinned-tag">{{ w.pinned }}</span> }</span>
        <button type="button" class="menu" [matMenuTriggerFor]="menu" [attr.aria-label]="w.actions" data-action="note-menu">⋯</button>
        <mat-menu #menu="matMenu">
          <button mat-menu-item type="button" (click)="startEdit()" data-action="note-edit">{{ w.edit }}</button>
          <button mat-menu-item type="button" (click)="togglePin()" data-action="note-pin">{{ note().pinned ? w.unpin : w.pin }}</button>
          <button mat-menu-item type="button" (click)="remove()" data-action="note-delete">{{ w.delete }}</button>
        </mat-menu>
      </div>
      @if (editing()) {
        <div class="edit">
          <textarea #box [value]="draft()" [attr.aria-label]="w.editLabel" (input)="draft.set(box.value)" (keydown)="key($event)"></textarea>
          <p class="hint">{{ w.hint }}</p>
          <div class="buttons">
            <button mat-flat-button type="button" (click)="save()" [disabled]="saving()" data-action="note-save">{{ w.save }}</button>
            <button mat-button type="button" (click)="editing.set(false)">{{ w.cancel }}</button>
          </div>
        </div>
      } @else if (note().text) {
        <p class="text">@for (s of segments(); track $index) {@if (s.mention; as m) {<a [routerLink]="['/world', m.kind, m.id]" [attr.data-mention]="m.id">{{ label(m.id) }}</a>} @else {<ng-container>{{ s.text }}</ng-container>}}</p>
      }
      @if (note().attachments.length) {
        <div class="images">
          @for (a of note().attachments; track a.id) {
            <a [href]="data().imageUrl(note().id, a.id)" target="_blank" rel="noopener"><img loading="lazy" [src]="data().imageUrl(note().id, a.id)" [alt]="w.image(a.name)" data-testid="note-image" /></a>
          }
        </div>
      }
      @if (problem(); as message) {
        <p class="error" role="alert">{{ message }}</p>
      }
    </article>
  `,
})
export class ProfileNote {
  readonly w = WORDS;
  private readonly confirm = inject(ConfirmService);

  readonly note = input.required<Note>();
  readonly data = input.required<NotesData>();
  readonly editing = signal(false);
  readonly draft = signal('');
  readonly saving = signal(false);
  readonly problem = signal<string | null>(null);
  private picked: EntityRef[] = [];
  private readonly box = viewChild<ElementRef<HTMLTextAreaElement>>('box');

  readonly segments = computed(() => splitMentions(this.note().text));
  readonly when = computed(() => formatTime(this.note().created_at));

  /** What a mention reads as: the entity's title, or its kind when it is not in the list (archived, say). */
  label(id: string): string {
    const e = this.data().byId().get(id);
    return `@${e ? e.title : WORDS.unknown}`;
  }

  startEdit(): void {
    const { text, picked } = toDraftText(this.note().text, this.data().byId());
    this.picked = picked;
    this.draft.set(text);
    this.problem.set(null);
    this.editing.set(true);
    setTimeout(() => this.box()?.nativeElement.focus());
  }

  key(event: KeyboardEvent): void {
    if (event.key === 'Escape') this.editing.set(false);
    else if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      void this.save();
    }
  }

  async save(): Promise<void> {
    this.saving.set(true);
    const text = toStoredText(this.draft(), this.picked);
    const problem = await this.data().edit(this.note().id, text);
    this.saving.set(false);
    this.problem.set(problem);
    if (!problem) this.editing.set(false);
  }

  async togglePin(): Promise<void> {
    this.problem.set(await this.data().setPinned(this.note().id, !this.note().pinned));
  }

  async remove(): Promise<void> {
    const yes = await this.confirm.ask({ title: WORDS.deleteTitle, message: WORDS.deleteMessage, confirmLabel: WORDS.delete, danger: true });
    if (yes) this.problem.set(await this.data().remove(this.note().id));
  }
}
