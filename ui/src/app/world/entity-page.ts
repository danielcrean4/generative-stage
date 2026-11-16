import { Component, HostListener, computed, effect, inject, signal, untracked } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { combineLatest, map } from 'rxjs';
import { ConfirmService } from './confirm';
import { EntityEditor } from './entity-editor';
import { LinksPanel } from './links-panel';
import { RevisionsPanel } from './revisions-panel';
import { SchemaFormView, FieldChange } from './schema-form-view';
import { HasUnsavedChanges } from './unsaved-changes.guard';
import { WorldApi } from './world-api';
import { formatTime } from './world-format';
import { Kind, Revision } from './world-models';
import { WorldGate } from './world-gate';
import { WorldProjectService } from './world-project.service';

/** The address of the form for a new entity: /world/<kind>/new. Real ids are UUIDs, so never clash. */
const NEW_ID = 'new';

/** Every word on this screen. */
const WORDS = {
  back: (plural: string) => `All ${plural.toLowerCase()}`,
  toProfile: 'Back to the profile',
  notFound: 'This project has no kind with that name.',
  newTitle: (kind: string) => `New ${kind.toLowerCase()}`,
  loading: 'Loading…',
  loadFailed: (label: string) => `Could not open this ${label.toLowerCase()}:`,
  revisionLine: (n: number, when: string) => `Revision ${n}, saved ${when}`,
  save: 'Save',
  saveNew: 'Create',
  saving: 'Saving…',
  discard: 'Discard changes',
  archive: 'Archive',
  restore: 'Restore',
  noteLabel: 'Note about this change (optional)',
  noteHint: 'Kept with the revision.',
  archivedBanner: 'This is archived and cannot be edited. Restore it to make changes.',
  conflictTitle: 'Someone else changed this while you were editing.',
  conflictBody: (latest: number | null) =>
    `${latest ? `It is now at revision ${latest}. ` : ''}Your changes are still in the form but have not been saved. Reload to see the latest, which throws your changes away, or keep editing and copy what you need first.`,
  conflictReload: 'Reload the latest',
  conflictKeep: 'Keep editing',
  viewingBanner: (n: number, when: string) => `You are looking at revision ${n}, saved ${when}. It cannot be edited here.`,
  viewingBack: 'Back to the current version',
  viewingRevert: 'Revert to this revision',
  leaveTitle: 'Leave without saving?',
  leaveMessage: 'You have changes that are not saved. If you leave, they are lost.',
  leaveConfirm: 'Leave and lose changes',
  stay: 'Keep editing',
  archiveTitle: 'Archive this and lose your unsaved changes?',
  archiveMessage: (label: string) => `The unsaved changes in the form will be lost. You can restore the archived ${label.toLowerCase()} later.`,
  archiveConfirm: 'Archive',
  revertTitle: (n: number) => `Revert to revision ${n}?`,
  revertMessage: (dirty: boolean) =>
    `This saves a new revision with the data from the old one. Nothing is lost: every revision stays in the list.${dirty ? '\n\nThe unsaved changes in the form will be lost.' : ''}`,
  revertConfirm: 'Revert',
  cancel: 'Cancel',
};

@Component({
  selector: 'app-entity-page',
  imports: [RouterLink, WorldGate, SchemaFormView, RevisionsPanel, LinksPanel, MatButtonModule, MatFormFieldModule, MatInputModule],
  styleUrl: './world-pages.scss',
  templateUrl: './entity-page.html',
  styles: `
    .layout { display: flex; gap: 2rem; align-items: flex-start; flex-wrap: wrap; }
    .main { flex: 1 1 30rem; min-width: 0; }
    .side { flex: 0 1 22rem; display: flex; flex-direction: column; gap: 1rem; }
    .banner { padding: 0.6rem 1rem; border-radius: 8px; margin: 0 0 0.75rem; max-width: 42rem; background: var(--mat-sys-surface-container-high); }
    .banner.warn { background: var(--mat-sys-error-container); color: var(--mat-sys-on-error-container); }
    .banner p { margin: 0 0 0.4rem; }
    .actions { display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center; margin-top: 0.5rem; }
    .meta { margin: 0; }
  `,
})
export class EntityPage implements HasUnsavedChanges {
  readonly w = WORDS;
  readonly world = inject(WorldProjectService);
  private readonly api = inject(WorldApi);
  private readonly router = inject(Router);
  private readonly confirm = inject(ConfirmService);
  private readonly route = inject(ActivatedRoute);

  private readonly params = toSignal(
    combineLatest([this.route.paramMap, this.route.data]).pipe(map(([p]) => ({ kind: p.get('kind'), id: p.get('id') }))),
    { initialValue: { kind: null as string | null, id: null as string | null } },
  );

  readonly kind = computed<Kind | null>(() => this.world.kind(this.params().kind));
  readonly editor = signal<EntityEditor | null>(null);

  constructor() {
    effect(() => {
      const kind = this.kind();
      const slug = this.world.slug();
      const id = this.params().id;
      untracked(() => {
        if (!kind || !slug) {
          this.editor.set(null);
          return;
        }
        const existing = this.editor();
        // Saving a new entity moves the address from /new to its id: the form is already right.
        if (existing && existing.kind.id === kind.id && existing.slug === slug && existing.entity()?.id === id) return;
        const editor = new EntityEditor(this.api, slug, kind);
        this.editor.set(editor);
        if (id && id !== NEW_ID) void editor.load(id);
        else editor.startNew();
      });
    });
  }

  when(iso: string): string {
    return formatTime(iso);
  }

  hasUnsavedChanges(): boolean {
    return this.editor()?.dirty() === true;
  }

  confirmLeave(): Promise<boolean> {
    return this.confirm.ask({
      title: WORDS.leaveTitle,
      message: WORDS.leaveMessage,
      confirmLabel: WORDS.leaveConfirm,
      cancelLabel: WORDS.stay,
    });
  }

  @HostListener('window:beforeunload', ['$event'])
  warnBeforeClosing(event: BeforeUnloadEvent): void {
    if (this.hasUnsavedChanges()) event.preventDefault();
  }

  edit(editor: EntityEditor, change: FieldChange): void {
    editor.edit(change.path, change.value);
  }

  setNote(editor: EntityEditor, event: Event): void {
    editor.note.set((event.target as HTMLInputElement).value);
  }

  async save(editor: EntityEditor): Promise<void> {
    const wasNew = editor.isNew();
    const saved = await editor.save();
    if (!saved) return;
    void this.world.refreshCounts();
    if (wasNew) await this.router.navigate(['/world', saved.kind, saved.id], { replaceUrl: true });
  }

  discard(editor: EntityEditor): void {
    editor.values.set(editor.baseline());
    editor.note.set('');
  }

  async archive(editor: EntityEditor): Promise<void> {
    if (editor.dirty()) {
      const ok = await this.confirm.ask({
        title: WORDS.archiveTitle,
        message: WORDS.archiveMessage(editor.kind.label),
        confirmLabel: WORDS.archiveConfirm,
        cancelLabel: WORDS.cancel,
      });
      if (!ok) return;
    }
    if (await editor.archive()) void this.world.refreshCounts();
  }

  async restore(editor: EntityEditor): Promise<void> {
    if (await editor.restore()) void this.world.refreshCounts();
  }

  async revert(editor: EntityEditor, revision: Revision): Promise<void> {
    const ok = await this.confirm.ask({
      title: WORDS.revertTitle(revision.revision),
      message: WORDS.revertMessage(editor.dirty()),
      confirmLabel: WORDS.revertConfirm,
      cancelLabel: WORDS.cancel,
    });
    if (ok) await editor.revert(revision.revision);
  }
}
