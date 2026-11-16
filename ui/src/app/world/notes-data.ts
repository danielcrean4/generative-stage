import { computed, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { EntityRef } from './notes-model';
import { toWorldError, WorldApi } from './world-api';
import { Note } from './world-models';

/**
 * What the profile page reads and writes about the notes of one entity: the notes (newest first)
 * and the project's entities, for mentions. Every write resolves an error message, or null.
 */
export class NotesData {
  readonly notes = signal<Note[]>([]);
  readonly entities = signal<EntityRef[]>([]);
  readonly error = signal<string | null>(null);
  readonly pinned = computed(() => this.notes().filter((n) => n.pinned));
  /** Entities by id, for turning a stored mention into a title. */
  readonly byId = computed(() => new Map(this.entities().map((e) => [e.id, e])));

  constructor(
    private readonly api: WorldApi,
    readonly slug: string,
    readonly entityId: string,
  ) {}

  async load(): Promise<void> {
    this.error.set(null);
    try {
      const [notes, entities] = await Promise.all([
        firstValueFrom(this.api.notes(this.slug, this.entityId)),
        firstValueFrom(this.api.entities(this.slug)),
      ]);
      this.notes.set(notes);
      this.entities.set(entities.map((e) => ({ id: e.id, kind: e.kind, title: e.title })));
    } catch (err) {
      this.error.set(toWorldError(err).message);
    }
  }

  private async reload(): Promise<void> {
    this.notes.set(await firstValueFrom(this.api.notes(this.slug, this.entityId)));
  }

  /** Post a note, then its images. If an image fails the half-made note is removed again. */
  async post(text: string, images: File[]): Promise<string | null> {
    let id: string | null = null;
    try {
      id = (await firstValueFrom(this.api.addNote(this.slug, this.entityId, text))).id;
      for (const file of images) await firstValueFrom(this.api.uploadNoteImage(this.slug, this.entityId, id, file, file.name || 'image'));
      await this.reload();
      return null;
    } catch (err) {
      if (id) await firstValueFrom(this.api.deleteNote(this.slug, this.entityId, id)).catch(() => undefined);
      return toWorldError(err).message;
    }
  }

  private async change(run: () => Promise<unknown>): Promise<string | null> {
    try {
      await run();
      await this.reload();
      return null;
    } catch (err) {
      return toWorldError(err).message;
    }
  }

  edit(noteId: string, text: string): Promise<string | null> {
    return this.change(() => firstValueFrom(this.api.updateNote(this.slug, this.entityId, noteId, { text })));
  }

  setPinned(noteId: string, pinned: boolean): Promise<string | null> {
    return this.change(() => firstValueFrom(this.api.updateNote(this.slug, this.entityId, noteId, { pinned })));
  }

  remove(noteId: string): Promise<string | null> {
    return this.change(() => firstValueFrom(this.api.deleteNote(this.slug, this.entityId, noteId)));
  }

  imageUrl(noteId: string, attachmentId: string): string {
    return this.api.noteImageUrl(this.slug, this.entityId, noteId, attachmentId);
  }
}
