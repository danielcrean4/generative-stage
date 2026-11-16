import { computed, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { FormErrors, FormField, buildFields, isDirty, mapError, pointerOf, setValue, toData } from './schema-form';
import { WorldApi, toWorldError } from './world-api';
import { Entity, JsonObject, Kind, Revision, WorldApiError } from './world-models';

/** What went wrong with the last action, told apart so the page can say the right thing. */
export interface EditorProblem {
  /** A message that fits no field (empty when the error sits on one). */
  general: string | null;
  errors: FormErrors;
}

/**
 * The state of one entity being created or edited, with no drawing in it. The page binds to the
 * signals and calls the methods; the rules that matter live here where they can be tested:
 *
 * - Save sends the revision that was read. If the API says someone else changed the entity
 *   (409 `revision_conflict`) nothing is overwritten: the edits stay in the form, `conflict`
 *   is set, and the person chooses to reload (discarding edits) or keep editing.
 * - Archive, restore and revert carry a revision too and go through the same conflict handling.
 * - `dirty` is true while the form differs from the saved entity; the route guard reads it.
 */
export class EntityEditor {
  readonly entity = signal<Entity | null>(null);
  readonly values = signal<JsonObject>({});
  readonly note = signal('');
  readonly loading = signal(false);
  readonly loadError = signal<WorldApiError | null>(null);
  readonly saving = signal(false);
  readonly problem = signal<EditorProblem>({ general: null, errors: { byPointer: {}, general: null } });
  /** Set when the API reported that the entity changed underneath us. */
  readonly conflict = signal<{ error: WorldApiError; latest: Entity | null } | null>(null);
  /** An older revision being looked at, read-only. */
  readonly viewing = signal<Revision | null>(null);

  readonly fields = computed<FormField[]>(() =>
    buildFields(this.kind.schema, { briefField: this.kind.brief_field }),
  );
  readonly isNew = computed(() => this.entity() === null);
  readonly archived = computed(() => this.entity()?.archived === true);
  readonly readonly = computed(() => this.archived() || this.viewing() !== null);
  readonly baseline = signal<JsonObject>({});
  readonly dirty = computed(() => isDirty(this.fields(), this.baseline(), this.values()));

  constructor(
    private readonly api: WorldApi,
    readonly slug: string,
    readonly kind: Kind,
  ) {}

  startNew(): void {
    this.entity.set(null);
    this.baseline.set({});
    this.values.set({});
    this.note.set('');
    this.clearProblem();
  }

  async load(id: string): Promise<void> {
    this.loading.set(true);
    this.loadError.set(null);
    try {
      this.adopt(await firstValueFrom(this.api.entity(this.slug, id)));
    } catch (err) {
      this.loadError.set(toWorldError(err));
    } finally {
      this.loading.set(false);
    }
  }

  /** Take an entity from the server as the new saved state and drop any edits. */
  private adopt(entity: Entity): void {
    this.entity.set(entity);
    this.baseline.set(entity.data);
    this.values.set(entity.data);
    this.note.set('');
    this.viewing.set(null);
    this.conflict.set(null);
    this.clearProblem();
  }

  private clearProblem(): void {
    this.problem.set({ general: null, errors: { byPointer: {}, general: null } });
  }

  edit(path: string[], value: unknown): void {
    if (this.readonly()) return;
    this.values.update((v) => setValue(v, path, value));
    // A field's message goes once the field is touched again.
    const pointer = pointerOf(path);
    const { byPointer } = this.problem().errors;
    if (pointer in byPointer) {
      const rest = { ...byPointer };
      delete rest[pointer];
      this.problem.update((p) => ({ ...p, errors: { ...p.errors, byPointer: rest } }));
    }
  }

  /** Run a call that carries a revision; a conflict is held, any other API error is shown. */
  private async guarded(action: () => Promise<Entity>): Promise<Entity | null> {
    this.saving.set(true);
    this.clearProblem();
    try {
      return await action();
    } catch (err) {
      const error = toWorldError(err);
      if (error.isConflict) {
        await this.holdConflict(error);
      } else {
        const errors = mapError(error, this.fields());
        this.problem.set({ general: errors.general ?? (Object.keys(errors.byPointer).length ? null : error.message), errors });
      }
      return null;
    } finally {
      this.saving.set(false);
    }
  }

  private async holdConflict(error: WorldApiError): Promise<void> {
    const id = this.entity()?.id;
    let latest: Entity | null = null;
    if (id) {
      try {
        latest = await firstValueFrom(this.api.entity(this.slug, id));
      } catch {
        latest = null;
      }
    }
    this.conflict.set({ error, latest });
  }

  /** Save the form: creates a new entity, or a new revision of this one. Resolves the saved entity. */
  async save(): Promise<Entity | null> {
    const data = toData(this.fields(), this.values());
    const note = this.note();
    const current = this.entity();
    const saved = await this.guarded(() =>
      current
        ? firstValueFrom(this.api.updateEntity(this.slug, current.id, current.revision, data, note))
        : firstValueFrom(this.api.createEntity(this.slug, this.kind.id, data, note)),
    );
    if (saved) this.adopt(saved);
    return saved;
  }

  /**
   * Save one field on its own, as a new revision: the saved data with only this field changed,
   * whatever else is in the form. Conflicts and field errors are handled as in `save`.
   */
  async saveField(path: string[], value: unknown, note = ''): Promise<Entity | null> {
    const current = this.entity();
    if (!current || this.readonly()) return null;
    const data = toData(this.fields(), setValue(this.baseline(), path, value));
    const saved = await this.guarded(() => firstValueFrom(this.api.updateEntity(this.slug, current.id, current.revision, data, note)));
    if (saved) this.adopt(saved);
    return saved;
  }

  async archive(): Promise<Entity | null> {
    const current = this.entity();
    if (!current) return null;
    const done = await this.guarded(() => firstValueFrom(this.api.archiveEntity(this.slug, current.id, current.revision)));
    if (done) this.adopt(done);
    return done;
  }

  async restore(): Promise<Entity | null> {
    const current = this.entity();
    if (!current) return null;
    const done = await this.guarded(() => firstValueFrom(this.api.restoreEntity(this.slug, current.id, current.revision)));
    if (done) this.adopt(done);
    return done;
  }

  /** Write a new revision holding an old revision's data. */
  async revert(to: number): Promise<Entity | null> {
    const current = this.entity();
    if (!current) return null;
    const done = await this.guarded(() => firstValueFrom(this.api.revertEntity(this.slug, current.id, current.revision, to)));
    if (done) this.adopt(done);
    return done;
  }

  /** The person chose to throw their edits away and take what is on the server now. */
  async reloadAfterConflict(): Promise<void> {
    const id = this.entity()?.id;
    this.conflict.set(null);
    if (id) await this.load(id);
  }

  /** The person chose to keep editing; the next save will meet the same conflict until they reload. */
  keepEditing(): void {
    this.conflict.set(null);
  }

  view(revision: Revision): void {
    this.viewing.set(revision);
  }

  closeView(): void {
    this.viewing.set(null);
  }

  /** What the form shows: an old revision while one is open, otherwise the working values. */
  readonly shownValues = computed<JsonObject>(() => this.viewing()?.data ?? this.values());
}
