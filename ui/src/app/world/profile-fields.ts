import { NgTemplateOutlet } from '@angular/common';
import { Component, ElementRef, computed, inject, input, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { EntityEditor } from './entity-editor';
import { FormField, getValue, parseNumber } from './schema-form';

/** Every word in this panel. */
const WORDS = {
  notSet: 'Not set',
  editTags: 'Edit tags',
  addTags: 'Add tags',
  yes: 'Yes',
  no: 'No',
  save: 'Save',
  saving: 'Saving…',
  cancel: 'Cancel',
  edit: (label: string) => `Edit ${label.toLowerCase()}`,
  noteLabel: 'Note about this change (optional)',
  tagsHint: 'Separate tags with commas.',
  fixed: 'This field cannot be edited here. Use the full form.',
  locked: 'This is archived. Restore it to make changes.',
};

interface Row {
  field: FormField;
  /** The label, with the name of its group in front for a field inside a group. */
  label: string;
}

function leaves(fields: FormField[], prefix = ''): Row[] {
  return fields.flatMap((f) => (f.type === 'group' ? leaves(f.children, `${f.label}: `) : [{ field: f, label: prefix + f.label }]));
}

/**
 * The identity block of the profile: the title, the brief, the tags and the other fields, each
 * edited in place on its own. Saving one field makes one revision, through the editor's
 * `saveField`, so a conflict or a field error shows the same way it does in the full form.
 */
@Component({
  selector: 'app-profile-fields',
  imports: [NgTemplateOutlet, MatButtonModule],
  styles: `
    :host { display: block; min-width: 0; }
    h1 { margin: 0; font-size: 1.6rem; overflow-wrap: anywhere; }
    .brief { margin: 0.5rem 0 0.75rem; white-space: pre-wrap; overflow-wrap: anywhere; }
    .tags { display: flex; flex-wrap: wrap; gap: 0.35rem; margin: 0.5rem 0; align-items: center; }
    .tag { font-size: 0.8rem; padding: 0.1rem 0.6rem; border-radius: 999px; background: var(--mat-sys-surface-container-high); }
    .rows { display: grid; grid-template-columns: minmax(6rem, auto) minmax(0, 1fr); gap: 0.35rem 1rem; margin: 0; }
    .rows dt { color: var(--mat-sys-on-surface-variant); }
    .rows dd { margin: 0; min-width: 0; overflow-wrap: anywhere; white-space: pre-wrap; }
    .value { all: unset; display: inline-block; max-width: 100%; cursor: text; border-bottom: 1px dashed transparent; overflow-wrap: anywhere; }
    .value:hover, .value:focus-visible { border-bottom-color: var(--mat-sys-outline); }
    .value.readonly { cursor: default; }
    .empty { opacity: 0.6; }
    .edit { display: flex; flex-direction: column; gap: 0.4rem; max-width: 36rem; margin: 0.25rem 0; }
    .edit input, .edit textarea, .edit select { font: inherit; padding: 0.35rem 0.5rem; border: 1px solid var(--mat-sys-primary); border-radius: 6px; background: var(--mat-sys-surface); color: inherit; width: 100%; box-sizing: border-box; }
    .edit .note { border-color: var(--mat-sys-outline-variant); font-size: 0.85rem; }
    .edit .buttons { display: flex; gap: 0.5rem; }
    .hint { font-size: 0.8rem; color: var(--mat-sys-on-surface-variant); margin: 0; }
    .field-error { color: var(--mat-sys-error); margin: 0; font-size: 0.85rem; }
    pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 0.85rem; }
  `,
  template: `
    @let ed = editor();
    @if (titleRow(); as t) {
      @if (editing() === t.field.pointer) {
        <ng-container *ngTemplateOutlet="edit; context: { $implicit: t.field }" />
      } @else {
        <h1><button class="value" [class.readonly]="locked()" [disabled]="locked()" [attr.data-edit]="t.field.pointer" [attr.aria-label]="w.edit(t.label)" (click)="start(t.field)">{{ text(t.field) || w.notSet }}</button></h1>
      }
    }
    @if (tagsRow(); as t) {
      @if (editing() === t.field.pointer) {
        <ng-container *ngTemplateOutlet="edit; context: { $implicit: t.field }" />
      } @else {
        <div class="tags" [attr.data-row]="t.field.pointer">
          @for (tag of tags(t.field); track tag) {
            <span class="tag">{{ tag }}</span>
          }
          <button class="value empty" [class.readonly]="locked()" [disabled]="locked()" [attr.data-edit]="t.field.pointer" [attr.aria-label]="w.edit(t.label)" (click)="start(t.field)">{{ tags(t.field).length ? w.editTags : w.addTags }}</button>
        </div>
      }
    }
    @if (briefRow(); as b) {
      @if (editing() === b.field.pointer) {
        <ng-container *ngTemplateOutlet="edit; context: { $implicit: b.field }" />
      } @else {
        <p class="brief" [attr.data-row]="b.field.pointer"><button class="value" [class.empty]="!text(b.field)" [class.readonly]="locked()" [disabled]="locked()" [attr.data-edit]="b.field.pointer" [attr.aria-label]="w.edit(b.label)" (click)="start(b.field)">{{ text(b.field) || w.notSet + ' (' + b.label.toLowerCase() + ')' }}</button></p>
      }
    }
    <dl class="rows">
      @for (r of otherRows(); track r.field.pointer) {
        <dt>{{ r.label }}</dt>
        <dd [attr.data-row]="r.field.pointer">
          @if (editing() === r.field.pointer) {
            <ng-container *ngTemplateOutlet="edit; context: { $implicit: r.field }" />
          } @else if (r.field.type === 'unsupported') {
            <pre>{{ json(r.field) }}</pre>
            <p class="hint">{{ w.fixed }}</p>
          } @else if (r.field.type === 'boolean') {
            <label><input type="checkbox" [checked]="get(r.field) === true" [disabled]="locked() || ed.saving()" [attr.data-edit]="r.field.pointer" (change)="toggle(r.field, $event)" /> {{ get(r.field) === true ? w.yes : w.no }}</label>
          } @else if (r.field.type === 'tags') {
            <button class="value" [class.empty]="tags(r.field).length === 0" [class.readonly]="locked()" [disabled]="locked()" [attr.data-edit]="r.field.pointer" [attr.aria-label]="w.edit(r.label)" (click)="start(r.field)">{{ tags(r.field).join(', ') || w.notSet }}</button>
          } @else {
            <button class="value" [class.empty]="!text(r.field)" [class.readonly]="locked()" [disabled]="locked()" [attr.data-edit]="r.field.pointer" [attr.aria-label]="w.edit(r.label)" (click)="start(r.field)">{{ text(r.field) || w.notSet }}</button>
          }
        </dd>
      }
    </dl>

    <ng-template #edit let-f>
      <form class="edit" [attr.data-editing]="f.pointer" (submit)="commit(f); $event.preventDefault()" (keydown.escape)="cancel()">
        @switch (f.type) {
          @case ('text') {
            <textarea rows="5" [attr.aria-label]="f.label" [value]="draft()" (input)="draft.set($any($event.target).value)" (keydown.control.enter)="commit(f)" (keydown.meta.enter)="commit(f)"></textarea>
          }
          @case ('enum') {
            <select [attr.aria-label]="f.label" (change)="draft.set($any($event.target).value)">
              <option value="" [selected]="draft() === ''"></option>
              @for (option of f.enumValues; track option) {
                <option [value]="option" [selected]="draft() === '' + option">{{ option }}</option>
              }
            </select>
          }
          @case ('number') {
            <input type="number" step="any" [attr.aria-label]="f.label" [value]="draft()" (input)="draft.set($any($event.target).value)" />
          }
          @case ('integer') {
            <input type="number" step="1" [attr.aria-label]="f.label" [value]="draft()" (input)="draft.set($any($event.target).value)" />
          }
          @default {
            <input type="text" [attr.aria-label]="f.label" [value]="draft()" (input)="draft.set($any($event.target).value)" />
          }
        }
        @if (f.type === 'tags') {
          <p class="hint">{{ w.tagsHint }}</p>
        }
        @if (ed.problem().errors.byPointer[f.pointer]; as message) {
          <p class="field-error" role="alert">{{ message }}</p>
        }
        @if (ed.problem().general; as message) {
          <p class="field-error" role="alert">{{ message }}</p>
        }
        <input class="note" type="text" maxlength="500" [attr.aria-label]="w.noteLabel" [placeholder]="w.noteLabel" [value]="note()" (input)="note.set($any($event.target).value)" />
        <div class="buttons">
          <button mat-flat-button type="submit" [disabled]="ed.saving()">{{ ed.saving() ? w.saving : w.save }}</button>
          <button mat-button type="button" (click)="cancel()">{{ w.cancel }}</button>
        </div>
      </form>
    </ng-template>
  `,
})
export class ProfileFields {
  readonly w = WORDS;
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  readonly editor = input.required<EntityEditor>();

  /** The pointer of the field being edited, if any. */
  readonly editing = signal<string | null>(null);
  readonly draft = signal('');
  readonly note = signal('');

  readonly locked = computed(() => this.editor().readonly());
  private readonly rows = computed(() => leaves(this.editor().fields()));
  readonly titleRow = computed(() => this.rows().find((r) => r.field.path.length === 1 && r.field.key === this.editor().kind.title_field) ?? null);
  readonly briefRow = computed(() => this.rows().find((r) => r.field.path.length === 1 && r.field.key === this.editor().kind.brief_field) ?? null);
  readonly tagsRow = computed(() => this.rows().find((r) => r.field.path.length === 1 && r.field.key === this.editor().kind.tags_field && r.field.type === 'tags') ?? null);
  readonly otherRows = computed(() => {
    const shown = new Set([this.titleRow(), this.briefRow(), this.tagsRow()].filter((r) => r !== null).map((r) => r.field.pointer));
    return this.rows().filter((r) => !shown.has(r.field.pointer));
  });

  get(field: FormField): unknown {
    return getValue(this.editor().baseline(), field.path);
  }

  text(field: FormField): string {
    const v = this.get(field);
    return v === undefined || v === null ? '' : String(v);
  }

  tags(field: FormField): string[] {
    const v = this.get(field);
    return Array.isArray(v) ? (v as string[]) : [];
  }

  json(field: FormField): string {
    const v = this.get(field);
    return v === undefined ? WORDS.notSet : JSON.stringify(v, null, 2);
  }

  start(field: FormField): void {
    if (this.locked()) return;
    this.draft.set(field.type === 'tags' ? this.tags(field).join(', ') : this.text(field));
    this.note.set('');
    this.editing.set(field.pointer);
    setTimeout(() => this.host.nativeElement.querySelector<HTMLElement>('form input:not(.note), form textarea, form select')?.focus());
  }

  cancel(): void {
    this.editing.set(null);
  }

  private value(field: FormField): unknown {
    const text = this.draft();
    switch (field.type) {
      case 'number':
      case 'integer':
        return parseNumber(text, field.type === 'integer');
      case 'enum': {
        if (text === '') return undefined;
        return field.enumValues.find((v) => String(v) === text) ?? text;
      }
      case 'tags':
        return [...new Set(text.split(',').map((t) => t.trim()).filter(Boolean))];
      default:
        return text === '' ? undefined : text;
    }
  }

  async commit(field: FormField): Promise<void> {
    const saved = await this.editor().saveField(field.path, this.value(field), this.note());
    if (saved) this.editing.set(null);
  }

  async toggle(field: FormField, event: Event): Promise<void> {
    await this.editor().saveField(field.path, (event.target as HTMLInputElement).checked);
  }
}
