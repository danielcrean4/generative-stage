import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { PromptView } from './prompt-view';
import { PromptPart } from './world-models';

const parts: PromptPart[] = [
  { text: 'a brass key', start: 0, end: 11, source: { kind: 'subject', id: 'j1', link: { type: 'entity', id: 'e1', kind: 'prop' } } },
  { text: ', ', start: 11, end: 13, source: { kind: 'glue', link: null } },
  { text: 'hand-sculpted clay', start: 13, end: 31, source: { kind: 'style_pack', id: 'clay', key: 'prompt.templates.prop', link: { type: 'style', id: 'prop.clay', changed: true } } },
  { text: ', plain white background', start: 31, end: 55, source: { kind: 'pipeline', id: 'prop', key: 'capture.background.words', link: null } },
];

describe('PromptView', () => {
  function setup(input: { parts: PromptPart[] | null; text: string | null }) {
    TestBed.configureTestingModule({ providers: [provideRouter([])] });
    const fixture = TestBed.createComponent(PromptView);
    fixture.componentRef.setInput('parts', input.parts);
    fixture.componentRef.setInput('text', input.text);
    fixture.componentRef.setInput('recordTitle', 'Key');
    fixture.detectChanges();
    return { fixture, el: fixture.nativeElement as HTMLElement };
  }

  it('shows each piece as a button with its label, the joining text plain, and a legend', () => {
    const { el } = setup({ parts, text: 'unused' });
    const buttons = [...el.querySelectorAll<HTMLButtonElement>('button.part')];
    expect(buttons.map((b) => b.dataset['tone'])).toEqual(['subject', 'style', 'capture']);
    expect(buttons[1].textContent).toContain('Style');
    expect(buttons[1].textContent).toContain('hand-sculpted clay');
    expect(el.querySelector('.glue')?.textContent).toBe(', ');
    expect(el.querySelectorAll('[data-testid="prompt-legend"] li')).toHaveLength(3);
    expect(el.querySelector('[data-testid="part-source"]')).toBeNull();
  });

  it('names the source of the piece pointed at or tapped, and links to its page', () => {
    const { fixture, el } = setup({ parts, text: null });
    el.querySelectorAll<HTMLButtonElement>('button.part')[1].dispatchEvent(new Event('mouseenter'));
    fixture.detectChanges();
    const card = el.querySelector('[data-testid="part-source"]')!;
    expect(card.textContent).toContain('The style pack "clay"');
    expect(card.textContent).toContain('has changed since the run');
    expect(card.querySelector('a')?.getAttribute('href')).toBe('/sources/style/prop.clay');
    el.querySelectorAll<HTMLButtonElement>('button.part')[0].click();
    fixture.detectChanges();
    expect(el.querySelector('[data-testid="part-source"] a')?.getAttribute('href')).toBe('/world/prop/e1');
    el.querySelectorAll<HTMLButtonElement>('button.part')[2].click();
    fixture.detectChanges();
    expect(el.querySelector('[data-testid="part-source"] a')).toBeNull(); // the pipeline's own words have no page
  });

  it('falls back to the plain text when no pieces were recorded', () => {
    const { el } = setup({ parts: null, text: 'a plain prompt' });
    expect(el.querySelector('button.part')).toBeNull();
    expect(el.querySelector('pre')?.textContent).toBe('a plain prompt');
  });
});
