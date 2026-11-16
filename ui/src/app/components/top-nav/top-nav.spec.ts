import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { WorldProjectService } from '../../world/world-project.service';
import { TopNav } from './top-nav';

describe('TopNav', () => {
  let fixture: ComponentFixture<TopNav>;
  let world: WorldProjectService;
  let el: HTMLElement;

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [TopNav], providers: [provideRouter([])] }).compileComponents();
    world = TestBed.inject(WorldProjectService);
    fixture = TestBed.createComponent(TopNav);
    el = fixture.nativeElement;
  });

  it('shows the current project as a link when it is the only one', () => {
    world.projects.set([{ slug: 'sample', name: 'Sample Project' } as never]);
    world.slug.set('sample');
    world.listStatus.set('ready');
    fixture.detectChanges();
    expect(el.querySelector('.world-name')?.textContent?.trim()).toBe('Sample Project');
    expect(el.querySelector('.world-trigger')).toBeNull();
  });

  it('asks for a project when the list is empty', () => {
    world.listStatus.set('ready');
    fixture.detectChanges();
    expect(el.querySelector('.world-name')?.textContent).toContain('No project');
  });
});
