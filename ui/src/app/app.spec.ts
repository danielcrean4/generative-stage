import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { App } from './app';
import { PRODUCT_NAME } from './brand';

describe('App', () => {
  let http: HttpTestingController;

  beforeEach(async () => {
    localStorage.clear();
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('should create the app', () => {
    const fixture = TestBed.createComponent(App);
    expect(fixture.componentInstance).toBeTruthy();
    http.match('/api/v1/projects');
  });

  it('shows the shell with the brand', async () => {
    const fixture = TestBed.createComponent(App);
    const el = fixture.nativeElement as HTMLElement;
    http.expectOne('/api/v1/projects').flush({ projects: [] });
    await fixture.whenStable();
    fixture.detectChanges();
    expect(el.querySelector('.brand')?.textContent).toBe(PRODUCT_NAME);
    expect(el.textContent).not.toContain('Earlier records');
  });

  it('shows the current world project in the bar and its kinds with counts in the sidebar, from the API', async () => {
    const fixture = TestBed.createComponent(App);
    const el = fixture.nativeElement as HTMLElement;
    http.expectOne('/api/v1/projects').flush({
      projects: [{ slug: 'sample', name: 'Sample Project', folder: '/x', project_file: '/x/studio.project.json', problem: null }],
    });
    (await vi.waitFor(() => http.expectOne('/api/v1/projects/sample/kinds'))).flush({
      kinds: [{ id: 'prop', label: 'Prop', plural_label: 'Props', icon: 'category', title_field: 'name', brief_field: 'brief', tags_field: 'tags', schema_file: 'p', schema: {} }],
    });
    http.expectOne('/api/v1/projects/sample/link-types').flush({ link_types: [] });
    (await vi.waitFor(() => http.expectOne('/api/v1/projects/sample/entities'))).flush({
      entities: [{ id: 'a', kind: 'prop' }, { id: 'b', kind: 'prop' }],
    });
    await fixture.whenStable();
    fixture.detectChanges();

    expect(el.querySelector('[data-testid="world-project"]')?.textContent).toContain('Sample Project');
    const nav = el.querySelector('a[data-kind="prop"]');
    expect(nav?.textContent).toContain('Props');
    expect(nav?.querySelector('.count')?.textContent?.trim()).toBe('2');
  });
});
