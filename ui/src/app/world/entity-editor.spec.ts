import { Observable, of, throwError } from 'rxjs';
import { EntityEditor } from './entity-editor';
import { unsavedChangesGuard } from './unsaved-changes.guard';
import { WorldApi } from './world-api';
import { Entity, JsonObject, Kind, WorldApiError } from './world-models';

const KIND: Kind = {
  id: 'prop',
  label: 'Prop',
  plural_label: 'Props',
  icon: 'category',
  title_field: 'name',
  brief_field: 'brief',
  tags_field: 'tags',
  schema_file: 'prop.schema.json',
  schema: {
    type: 'object',
    required: ['name'],
    properties: {
      name: { type: 'string' },
      brief: { type: 'string' },
      tags: { type: 'array', items: { type: 'string' } },
      material: { type: 'string' },
    },
  },
};

function entity(revision: number, data: JsonObject, archived = false): Entity {
  return { id: 'e1', kind: 'prop', revision, archived, title: String(data['name']), data, created_at: 't0', updated_at: `t${revision}` };
}

const conflict = () => new WorldApiError(409, 'revision_conflict', 'changed underneath', null);

/** A stand-in for the API: each method is a spy that answers from a script. */
function fakeApi() {
  const api = {
    entity: vi.fn((): Observable<Entity> => of(entity(1, { name: 'Key' }))),
    createEntity: vi.fn((): Observable<Entity> => of(entity(1, { name: 'Key' }))),
    updateEntity: vi.fn((): Observable<Entity> => of(entity(2, { name: 'Key', material: 'steel' }))),
    archiveEntity: vi.fn((): Observable<Entity> => of(entity(2, { name: 'Key' }, true))),
    restoreEntity: vi.fn((): Observable<Entity> => of(entity(3, { name: 'Key' }))),
    revertEntity: vi.fn((): Observable<Entity> => of(entity(3, { name: 'Key' }))),
  };
  return api;
}

async function opened(api = fakeApi()) {
  const editor = new EntityEditor(api as unknown as WorldApi, 'sample', KIND);
  await editor.load('e1');
  return { api, editor };
}

describe('EntityEditor', () => {
  it('starts clean and becomes dirty when a field changes, and clean again when it is put back', async () => {
    const { editor } = await opened();
    expect(editor.dirty()).toBe(false);
    editor.edit(['material'], 'steel');
    expect(editor.dirty()).toBe(true);
    editor.edit(['material'], '');
    expect(editor.dirty()).toBe(false);
  });

  it('creates a new entity from the form and takes the saved one as its baseline', async () => {
    const api = fakeApi();
    const editor = new EntityEditor(api as unknown as WorldApi, 'sample', KIND);
    editor.startNew();
    expect(editor.isNew()).toBe(true);
    editor.edit(['name'], 'Key');
    expect(editor.dirty()).toBe(true);
    const saved = await editor.save();
    expect(api.createEntity).toHaveBeenCalledWith('sample', 'prop', { name: 'Key' }, '');
    expect(saved?.id).toBe('e1');
    expect(editor.isNew()).toBe(false);
    expect(editor.dirty()).toBe(false);
  });

  it('saves with the revision it read and the note, and is clean afterwards', async () => {
    const { api, editor } = await opened();
    editor.edit(['material'], 'steel');
    editor.note.set('Steel, not iron');
    await editor.save();
    expect(api.updateEntity).toHaveBeenCalledWith('sample', 'e1', 1, { name: 'Key', material: 'steel' }, 'Steel, not iron');
    expect(editor.entity()?.revision).toBe(2);
    expect(editor.dirty()).toBe(false);
    expect(editor.note()).toBe('');
  });

  it('shows a validation error on the field the API names, and keeps the edits', async () => {
    const { api, editor } = await opened();
    api.updateEntity.mockReturnValueOnce(
      throwError(() => new WorldApiError(422, 'invalid_entity', "/data/name: '' should be non-empty", '/data/name')),
    );
    editor.edit(['name'], '');
    expect(await editor.save()).toBeNull();
    expect(editor.problem().errors.byPointer).toEqual({ '/data/name': "'' should be non-empty" });
    expect(editor.problem().general).toBeNull();
    expect(editor.values()['name']).toBe('');
    // Touching the field clears its message.
    editor.edit(['name'], 'x');
    expect(editor.problem().errors.byPointer).toEqual({});
  });

  it('shows a general message for an error that fits no field', async () => {
    const { api, editor } = await opened();
    api.updateEntity.mockReturnValueOnce(throwError(() => new WorldApiError(409, 'entity_archived', 'It is archived.', null)));
    editor.edit(['material'], 'x');
    await editor.save();
    expect(editor.problem().general).toBe('It is archived.');
  });

  describe('a concurrent change (409 revision_conflict)', () => {
    it('holds the conflict, keeps the edits, and does not retry or overwrite', async () => {
      const { api, editor } = await opened();
      api.updateEntity.mockReturnValueOnce(throwError(conflict));
      api.entity.mockReturnValueOnce(of(entity(2, { name: 'Key', material: 'iron' })));
      editor.edit(['material'], 'steel');
      expect(await editor.save()).toBeNull();

      expect(editor.conflict()?.latest?.revision).toBe(2);
      expect(editor.values()['material']).toBe('steel');
      expect(editor.entity()?.revision).toBe(1);
      expect(api.updateEntity).toHaveBeenCalledTimes(1);
      expect(editor.dirty()).toBe(true);
    });

    it('reloading takes the server version and drops the edits', async () => {
      const { api, editor } = await opened();
      api.updateEntity.mockReturnValueOnce(throwError(conflict));
      api.entity.mockReturnValue(of(entity(2, { name: 'Key', material: 'iron' })));
      editor.edit(['material'], 'steel');
      await editor.save();
      await editor.reloadAfterConflict();
      expect(editor.conflict()).toBeNull();
      expect(editor.entity()?.revision).toBe(2);
      expect(editor.values()['material']).toBe('iron');
      expect(editor.dirty()).toBe(false);
    });

    it('keep editing leaves the edits and the old revision, so the next save meets the conflict again', async () => {
      const { api, editor } = await opened();
      api.updateEntity.mockReturnValue(throwError(conflict));
      editor.edit(['material'], 'steel');
      await editor.save();
      editor.keepEditing();
      expect(editor.conflict()).toBeNull();
      expect(editor.values()['material']).toBe('steel');
      await editor.save();
      expect(editor.conflict()).not.toBeNull();
      expect(api.updateEntity).toHaveBeenLastCalledWith('sample', 'e1', 1, expect.anything(), '');
    });

    it('archive, restore and revert are held the same way', async () => {
      const { api, editor } = await opened();
      api.archiveEntity.mockReturnValueOnce(throwError(conflict));
      expect(await editor.archive()).toBeNull();
      expect(editor.conflict()).not.toBeNull();
      editor.keepEditing();

      api.restoreEntity.mockReturnValueOnce(throwError(conflict));
      await editor.restore();
      expect(editor.conflict()).not.toBeNull();
      editor.keepEditing();

      api.revertEntity.mockReturnValueOnce(throwError(conflict));
      await editor.revert(1);
      expect(editor.conflict()).not.toBeNull();
      expect(editor.entity()?.revision).toBe(1);
    });
  });

  it('archives, which makes the form read-only, and restores', async () => {
    const { editor } = await opened();
    await editor.archive();
    expect(editor.archived()).toBe(true);
    expect(editor.readonly()).toBe(true);
    editor.edit(['material'], 'ignored');
    expect(editor.values()['material']).toBeUndefined();
    await editor.restore();
    expect(editor.archived()).toBe(false);
    expect(editor.readonly()).toBe(false);
  });

  it('reverts by asking for a new revision, sending the current one and the one to copy', async () => {
    const { api, editor } = await opened();
    await editor.revert(1);
    expect(api.revertEntity).toHaveBeenCalledWith('sample', 'e1', 1, 1);
    expect(editor.entity()?.revision).toBe(3);
  });

  it('shows an old revision read-only without touching the working copy', async () => {
    const { editor } = await opened();
    editor.edit(['material'], 'steel');
    editor.view({ entity_id: 'e1', revision: 1, archived: false, data: { name: 'Old name' }, note: null, created_at: 't' });
    expect(editor.shownValues()['name']).toBe('Old name');
    expect(editor.readonly()).toBe(true);
    editor.edit(['name'], 'ignored');
    editor.closeView();
    expect(editor.shownValues()['material']).toBe('steel');
    expect(editor.values()['name']).toBe('Key');
  });

  it('reports a load failure', async () => {
    const api = fakeApi();
    api.entity.mockReturnValueOnce(throwError(() => new WorldApiError(404, 'entity_not_found', 'no such entity', null)));
    const editor = new EntityEditor(api as unknown as WorldApi, 'sample', KIND);
    await editor.load('missing');
    expect(editor.loadError()?.code).toBe('entity_not_found');
    expect(editor.entity()).toBeNull();
  });
});

describe('unsavedChangesGuard', () => {
  const run = (page: { hasUnsavedChanges(): boolean; confirmLeave(): Promise<boolean> }) =>
    (unsavedChangesGuard as unknown as (p: typeof page) => Promise<boolean>)(page);

  it('lets a clean page go without asking', async () => {
    const confirmLeave = vi.fn(async () => false);
    expect(await run({ hasUnsavedChanges: () => false, confirmLeave })).toBe(true);
    expect(confirmLeave).not.toHaveBeenCalled();
  });

  it('asks when there are unsaved changes, and goes only if the person agrees', async () => {
    expect(await run({ hasUnsavedChanges: () => true, confirmLeave: async () => false })).toBe(false);
    expect(await run({ hasUnsavedChanges: () => true, confirmLeave: async () => true })).toBe(true);
  });
});

describe('EntityEditor.saveField', () => {
  it('saves only the one field, as a new revision, from the saved data', async () => {
    const { api, editor } = await opened();
    editor.edit(['name'], 'Unsaved other edit');
    await editor.saveField(['material'], 'steel', 'more exact');
    expect(api.updateEntity).toHaveBeenCalledWith('sample', 'e1', 1, { name: 'Key', material: 'steel' }, 'more exact');
    expect(editor.entity()?.revision).toBe(2);
    expect(editor.dirty()).toBe(false);
  });

  it('leaves a cleared optional field out of the data', async () => {
    const api = fakeApi();
    api.entity.mockReturnValue(of(entity(1, { name: 'Key', material: 'steel' })));
    const { editor } = await opened(api);
    await editor.saveField(['material'], undefined);
    expect(api.updateEntity).toHaveBeenCalledWith('sample', 'e1', 1, { name: 'Key' }, '');
  });

  it('holds a conflict and a field error the same way a save does', async () => {
    const { api, editor } = await opened();
    api.updateEntity.mockReturnValueOnce(throwError(conflict));
    expect(await editor.saveField(['material'], 'steel')).toBeNull();
    expect(editor.conflict()).not.toBeNull();
    editor.keepEditing();
    api.updateEntity.mockReturnValueOnce(throwError(() => new WorldApiError(422, 'invalid_entity', 'too short', '/data/name')));
    expect(await editor.saveField(['name'], '')).toBeNull();
    expect(editor.problem().errors.byPointer['/data/name']).toBe('too short');
  });

  it('does nothing for an archived entity', async () => {
    const api = fakeApi();
    api.entity.mockReturnValue(of(entity(2, { name: 'Key' }, true)));
    const { editor } = await opened(api);
    expect(await editor.saveField(['material'], 'steel')).toBeNull();
    expect(api.updateEntity).not.toHaveBeenCalled();
  });
});
