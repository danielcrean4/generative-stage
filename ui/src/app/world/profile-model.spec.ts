import { baseName, buildStream, candidateItems, changedFields, filterStream, fileKind, fitsSlot, freshness, slotLabel, slotsOf, traceQuery } from './profile-model';
import { AttachedRun, Choice, JobView, Note, Revision } from './world-models';

function rev(revision: number, data: Record<string, unknown>, created_at: string, extra: Partial<Revision> = {}): Revision {
  return { entity_id: 'e1', revision, archived: false, data, note: null, created_at, ...extra };
}

function choice(slot: string, run_id: string, candidate: string, chosen_at: string, entity_revision = 1): Choice {
  return { entity_id: 'e1', slot, run_id, candidate, entity_revision, note: null, chosen_at };
}

const label = (key: string) => key.toUpperCase();

describe('profile model', () => {
  it('tells files apart by name, not by slot', () => {
    expect(fileKind('attempts/a/concept/final.PNG')).toBe('image');
    expect(fileKind('mesh.glb')).toBe('model');
    expect(fileKind('notes.txt')).toBe('other');
    expect(baseName('a/b/c.png')).toBe('c.png');
    expect(slotLabel('mesh')).toBe('3D');
    expect(slotLabel('side_view')).toBe('Side view');
  });

  it('always offers main, 3D and icon, then any other chosen slot by name', () => {
    expect(slotsOf({})).toEqual(['main', 'mesh', 'icon']);
    const c = choice('x', 'r', 'a.png', 't');
    expect(slotsOf({ side: c, icon: c, back: c })).toEqual(['main', 'mesh', 'icon', 'back', 'side']);
  });

  it('lists job candidates and earlier choices once each, newest first', () => {
    const jobs: JobView[] = [
      {
        job: { id: 'run-1', entity_id: 'e1', entity_revision: 1 },
        candidates: [
          { id: 'c1', job_id: 'run-1', candidate: 'a.png', verdict: 'pass', note: '', created_at: '2026-01-01' },
          { id: 'c2', job_id: 'run-1', candidate: null, verdict: null, note: '', created_at: '2026-01-02' },
          { id: 'c3', job_id: 'run-1', candidate: 'b.glb', verdict: 'review', note: '', created_at: '2026-01-03' },
        ],
      },
    ];
    const items = candidateItems(jobs, [choice('main', 'run-1', 'a.png', '2026-01-05'), choice('main', 'run-9', 'old.png', '2026-01-04')]);
    expect(items.map((i) => `${i.runId}/${i.candidate}`)).toEqual(['run-9/old.png', 'run-1/b.glb', 'run-1/a.png']);
    expect(items.find((i) => i.candidate === 'a.png')?.verdict).toBe('pass');
    expect(items.filter((i) => fitsSlot(i, 'mesh')).map((i) => i.candidate)).toEqual(['b.glb']);
    expect(items.filter((i) => fitsSlot(i, 'main')).map((i) => i.candidate)).toEqual(['old.png', 'a.png']);
    expect(items.filter((i) => fitsSlot(i, 'icon')).map((i) => i.candidate)).toEqual(['a.png']);
  });

  it('names the fields that differ and what they changed from and to', () => {
    expect(changedFields({ a: 'x', b: 1 }, { a: 'x', b: 2, c: 'new' }, label)).toEqual([
      { key: 'b', label: 'B', before: '1', after: '2' },
      { key: 'c', label: 'C', before: 'empty', after: 'new' },
    ]);
  });

  it('merges revisions, runs and choices into one stream, newest first', () => {
    const revisions = [rev(1, { a: 'x' }, '2026-01-01'), rev(2, { a: 'y' }, '2026-01-03', { note: 'better' }), rev(3, { a: 'y' }, '2026-01-06', { archived: true })];
    const runs: AttachedRun[] = [{ entity_id: 'e1', run_id: 'abcdefghijkl', entity_revision: 2, note: 'made by a job', attached_at: '2026-01-04' }];
    const choices = [choice('mesh', 'abcdefghijkl', 'attempts/a/mesh/m.glb', '2026-01-05', 2), choice('main', 'abcdefghijkl', 'c.png', '2026-01-04T12')];
    const stream = buildStream(revisions, runs, choices, label);
    expect(stream.map((e) => e.id)).toEqual(['revision-3', 'choice-mesh-2026-01-05', 'choice-main-2026-01-04T12', 'run-abcdefghijkl', 'revision-2', 'revision-1']);
    expect(stream[0].title).toBe('Revision 3: archived');
    expect(stream[4].changes).toEqual([{ key: 'a', label: 'A', before: 'x', after: 'y' }]);
    expect(stream[4].note).toBe('better');
    expect(stream[1].thumb).toBeNull();
    expect(stream[2].thumb).toEqual({ runId: 'abcdefghijkl', candidate: 'c.png' });
    expect(stream[2].title).toBe('Chose c.png from run abcdefgh… as image');
    expect(stream[5].title).toBe('Created at revision 1');
    expect(filterStream(stream, 'change').map((e) => e.kind)).toEqual(['change', 'change', 'change']);
    expect(filterStream(stream, 'run').map((e) => e.kind)).toEqual(['choice', 'choice', 'run']);
    expect(filterStream(stream, 'all')).toHaveLength(6);
  });

  it('says how the entity moved on since a choice, or nothing when the revision is unknown', () => {
    const revisions = [rev(1, { a: 'x' }, 't1'), rev(2, { a: 'x', b: 'z' }, 't2')];
    const found = freshness(choice('main', 'r', 'a.png', 't', 1), 2, revisions, label);
    expect(found?.changed.map((c) => c.key)).toEqual(['b']);
    expect(freshness(choice('main', 'r', 'a.png', 't', 1), 1, revisions, label)?.changed).toEqual([]);
    expect(freshness(choice('main', 'r', 'a.png', 't', 7), 2, revisions, label)).toBeNull();
  });

  it('interleaves notes by time and gives them their own filter', () => {
    const note = (id: string, created_at: string): Note => ({ id, created_at, updated_at: created_at, text: id, pinned: false, mentions: [], attachments: [] });
    const revisions = [rev(1, { name: 'a' }, '2026-01-01T00:00:00Z'), rev(2, { name: 'b' }, '2026-01-03T00:00:00Z')];
    const stream = buildStream(revisions, [], [], label, [note('n1', '2026-01-02T00:00:00Z'), note('n2', '2026-01-04T00:00:00Z')]);
    expect(stream.map((e) => e.id)).toEqual(['note-n2', 'revision-2', 'note-n1', 'revision-1']);
    expect(filterStream(stream, 'note').map((e) => e.noteItem?.id)).toEqual(['n2', 'n1']);
    expect(filterStream(stream, 'change').map((e) => e.kind)).toEqual(['change', 'change']);
    expect(filterStream(stream, 'run')).toEqual([]);
  });
});

describe('traceQuery', () => {
  it('names the attempt and stage a candidate came from', () => {
    expect(traceQuery('attempts/a1/shape/mesh/mesh.glb')).toEqual({ attempt: 'a1', stage: 'shape' });
    expect(traceQuery('key.glb')).toEqual({});
  });
});
