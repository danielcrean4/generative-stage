import { EntityRef, imageProblem, insertMention, matchEntities, mentionTrigger, splitMentions, toDraftText, toStoredText } from './notes-model';

const mechanic: EntityRef = { id: 'c-1', kind: 'character', title: 'Mechanic' };
const bench: EntityRef = { id: 'p-2', kind: 'prop', title: 'Workshop bench' };

describe('notes model', () => {
  it('cuts a stored text into text and mentions', () => {
    expect(splitMentions('ask @character/c-1 about @prop/p-2.')).toEqual([
      { text: 'ask ', mention: null },
      { text: '', mention: { kind: 'character', id: 'c-1' } },
      { text: ' about ', mention: null },
      { text: '', mention: { kind: 'prop', id: 'p-2' } },
      { text: '.', mention: null },
    ]);
    expect(splitMentions('plain, with an email a@b.c')).toEqual([{ text: 'plain, with an email a@b.c', mention: null }]);
  });

  it('sees an @word being typed only at a word start', () => {
    expect(mentionTrigger('hi @Mec', 7)).toEqual({ start: 3, query: 'Mec' });
    expect(mentionTrigger('@', 1)).toEqual({ start: 0, query: '' });
    expect(mentionTrigger('mail me@exam', 12)).toBeNull();
    expect(mentionTrigger('hi @Mec rest', 12)).toBeNull();
    expect(mentionTrigger('hi @Mec rest', 7)).toEqual({ start: 3, query: 'Mec' });
  });

  it('offers titles that start with the query first, then ones that contain it', () => {
    const all = [bench, mechanic, { id: 'x', kind: 'prop', title: 'Old mechanism' }];
    expect(matchEntities(all, 'mech').map((e) => e.title)).toEqual(['Mechanic', 'Old mechanism']);
    expect(matchEntities(all, '').length).toBe(3);
    expect(matchEntities(all, 'zzz')).toEqual([]);
  });

  it('turns a pick into @Title and back into the stored form', () => {
    const next = insertMention('hi @Mec', { start: 3, query: 'Mec' }, 7, 'Mechanic');
    expect(next).toEqual({ text: 'hi @Mechanic ', caret: 13 });
    expect(toStoredText('  hi @Mechanic and @Workshop bench ', [mechanic, bench])).toBe('hi @character/c-1 and @prop/p-2');
  });

  it('shows a stored text as a draft with titles, and keeps unknown mentions as they are', () => {
    const known = new Map([mechanic, bench].map((e) => [e.id, e]));
    const draft = toDraftText('@character/c-1 and @prop/nope and @prop/c-1', known);
    expect(draft.text).toBe('@Mechanic and @prop/nope and @prop/c-1');
    expect(draft.picked).toEqual([mechanic]);
  });

  it('refuses images the server would refuse', () => {
    expect(imageProblem({ type: 'image/png', size: 10 })).toBeNull();
    expect(imageProblem({ type: 'image/webp', size: 10 })).toBeNull();
    expect(imageProblem({ type: 'image/gif', size: 10 })).toMatch(/png, jpeg and webp/);
    expect(imageProblem({ type: 'image/png', size: 6 * 1024 * 1024 })).toMatch(/5 MB/);
  });
});
