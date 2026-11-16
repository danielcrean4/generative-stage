import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { WorldProjectService } from '../../world/world-project.service';
import { Kind } from '../../world/world-models';
import { LeftNav } from './left-nav';

describe('LeftNav', () => {
  let fixture: ComponentFixture<LeftNav>;
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [LeftNav],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(LeftNav);
    await fixture.whenStable();
    fixture.detectChanges();
  });

  afterEach(() => http.verify());

  it('should create', () => {
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('links to the docs view', () => {
    const docs = Array.from(
      fixture.nativeElement.querySelectorAll('a') as NodeListOf<HTMLAnchorElement>,
    ).find((a) => a.textContent?.includes('Docs'));
    expect(docs?.getAttribute('href')).toBe('/docs');
  });

  it('groups the kinds by family, Other last, and badges a script kind with its form', () => {
    const kind = (id: string, extra: Partial<Kind> = {}): Kind => ({
      id, label: id, plural_label: id + 's', icon: '', title_field: 'name', brief_field: null, tags_field: null, schema_file: '', schema: {}, ...extra,
    });
    TestBed.inject(WorldProjectService).kinds.set([
      kind('scene', { family: 'script', form: 'linear' }),
      kind('hint'),
      kind('room', { family: 'setting' }),
      kind('cup', { family: 'prop' }),
    ]);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const groups = Array.from(el.querySelectorAll('[data-family]')).map((g) => [
      g.querySelector('.family-label')?.textContent?.trim(),
      Array.from(g.querySelectorAll('a[data-kind]')).map((a) => a.getAttribute('data-kind')),
    ]);
    expect(groups).toEqual([
      ['Props', ['cup']],
      ['Settings', ['room']],
      ['Scripts', ['scene']],
      ['Other', ['hint']],
    ]);
    expect(el.querySelector('a[data-kind="scene"] .form-badge')?.textContent?.trim()).toBe('linear');
    expect(el.querySelector('a[data-kind="cup"] .form-badge')).toBeNull();
    expect(el.querySelector('[data-nav="story"]')?.textContent).toContain('Story graph');
  });

  it('has no list of earlier records and no roadmap modules', () => {
    const text = fixture.nativeElement.textContent as string;
    expect(text).not.toContain('Earlier records');
    expect(text).toContain('Runs');
  });
});
