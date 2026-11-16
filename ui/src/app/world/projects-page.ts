import { Component, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { ConfirmService } from './confirm';
import { stripPointer } from './schema-form';
import { toWorldError } from './world-api';
import { WorldProject } from './world-models';
import { WorldProjectService } from './world-project.service';

/** Every word on this screen. */
const WORDS = {
  title: 'Projects',
  listLabel: 'Projects',
  intro:
    'A project is a folder you own. It holds a world: its kinds, its entities and the links between them. Pick the one to work in, make a new one, or open one that already exists.',
  loading: 'Loading projects…',
  none: 'No projects yet. Make one below, or open a project file you already have.',
  current: 'Current',
  use: 'Use this project',
  remove: 'Remove from list',
  slugHint: 'Lowercase letters, digits and hyphens, starting with a letter.',
  folderLabel: 'Folder',
  slugLabel: 'Short name',
  nameLabel: 'Name',
  fileLabel: 'Project file',
  createTitle: 'Make a new project',
  createHelp: 'The folder must be an absolute path that does not exist yet or is empty. The default kinds (setting, character, prop, script) are copied into it.',
  createButton: 'Make project',
  creating: 'Making…',
  openTitle: 'Open an existing project',
  openHelp: 'The path of a studio.project.json file. It is added to this list; nothing in its folder changes.',
  openButton: 'Open project',
  opening: 'Opening…',
  removeTitle: (name: string) => `Remove "${name}" from the list?`,
  removeMessage: (folder: string | undefined) =>
    `This only takes the project off this list. The folder${folder ? ` (${folder})` : ''} and everything in it stay exactly as they are, and you can open it again later.`,
  removeConfirm: 'Remove from list',
  keep: 'Keep it',
  problemPrefix: 'Cannot be loaded: ',
  unreachable: 'The world model could not be reached: ',
};

function slugify(name: string): string {
  const base = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return /^[a-z]/.test(base) ? base.slice(0, 49) : base ? ('p-' + base).slice(0, 49) : '';
}

@Component({
  selector: 'app-projects-page',
  imports: [MatButtonModule, MatFormFieldModule, MatInputModule],
  styleUrl: './world-pages.scss',
  template: `
    <section class="world-page" data-page="projects">
      <header class="page-head">
        <h2>{{ w.title }}</h2>
      </header>
      <p class="intro">{{ w.intro }}</p>

      @if (world.listStatus() === 'loading') {
        <p class="muted">{{ w.loading }}</p>
      } @else if (world.listError(); as e) {
        <p class="error" role="alert">{{ w.unreachable }}{{ e.message }}</p>
      } @else {
        @if (world.projects().length === 0) {
          <p class="muted empty" data-testid="no-projects">{{ w.none }}</p>
        } @else {
          <ul class="cards" [attr.aria-label]="w.listLabel">
            @for (p of world.projects(); track p.slug) {
              <li class="card" [class.is-current]="p.slug === world.slug()" [attr.data-project]="p.slug">
                <div class="card-main">
                  <strong class="card-title">{{ p.name ?? p.slug }}</strong>
                  <span class="muted">{{ p.slug }}</span>
                  @if (p.folder) {
                    <span class="muted path">{{ p.folder }}</span>
                  }
                  @if (p.problem) {
                    <span class="error" role="alert">{{ w.problemPrefix }}{{ p.problem }}</span>
                  }
                </div>
                <div class="card-actions">
                  @if (p.slug === world.slug()) {
                    <span class="badge">{{ w.current }}</span>
                  } @else if (!p.problem) {
                    <button mat-stroked-button (click)="use(p)">{{ w.use }}</button>
                  }
                  <button mat-button (click)="askRemove(p)">{{ w.remove }}</button>
                </div>
              </li>
            }
          </ul>
        }
        @if (actionError()) {
          <p class="error" role="alert">{{ actionError() }}</p>
        }

        <div class="forms">
          <form class="panel" (submit)="$event.preventDefault(); create()" data-form="create">
            <h3>{{ w.createTitle }}</h3>
            <p class="hint">{{ w.createHelp }}</p>
            <mat-form-field appearance="outline" class="wide">
              <mat-label>{{ w.nameLabel }}</mat-label>
              <input matInput name="name" [value]="name()" (input)="setName($event)" required />
            </mat-form-field>
            @if (createErrors()['/name']; as m) {
              <p class="field-error" role="alert">{{ m }}</p>
            }
            <mat-form-field appearance="outline" class="wide">
              <mat-label>{{ w.slugLabel }}</mat-label>
              <input matInput name="slug" [value]="slug()" (input)="setSlug($event)" required />
              <mat-hint>{{ w.slugHint }}</mat-hint>
            </mat-form-field>
            @if (createErrors()['/slug']; as m) {
              <p class="field-error" role="alert">{{ m }}</p>
            }
            <mat-form-field appearance="outline" class="wide">
              <mat-label>{{ w.folderLabel }}</mat-label>
              <input matInput name="folder" [value]="folder()" (input)="folder.set(text($event))" required />
            </mat-form-field>
            @if (createErrors()['/folder']; as m) {
              <p class="field-error" role="alert">{{ m }}</p>
            }
            @if (createErrors()['general']; as m) {
              <p class="error" role="alert">{{ m }}</p>
            }
            <button mat-flat-button type="submit" [disabled]="busy()">{{ busy() === 'create' ? w.creating : w.createButton }}</button>
          </form>

          <form class="panel" (submit)="$event.preventDefault(); open()" data-form="open">
            <h3>{{ w.openTitle }}</h3>
            <p class="hint">{{ w.openHelp }}</p>
            <mat-form-field appearance="outline" class="wide">
              <mat-label>{{ w.fileLabel }}</mat-label>
              <input matInput name="project_file" [value]="file()" (input)="file.set(text($event))" required />
            </mat-form-field>
            @if (openError()) {
              <p class="error" role="alert">{{ openError() }}</p>
            }
            <button mat-flat-button type="submit" [disabled]="busy()">{{ busy() === 'open' ? w.opening : w.openButton }}</button>
          </form>
        </div>
      }
    </section>
  `,
})
export class ProjectsPage {
  readonly w = WORDS;
  readonly world = inject(WorldProjectService);
  private readonly confirm = inject(ConfirmService);

  readonly name = signal('');
  readonly slug = signal('');
  readonly folder = signal('');
  readonly file = signal('');
  private slugTouched = false;
  readonly busy = signal<'create' | 'open' | null>(null);
  readonly createErrors = signal<Record<string, string>>({});
  readonly openError = signal<string | null>(null);
  readonly actionError = signal<string | null>(null);

  text(event: Event): string {
    return (event.target as HTMLInputElement).value;
  }

  setName(event: Event): void {
    this.name.set(this.text(event));
    if (!this.slugTouched) this.slug.set(slugify(this.name()));
  }

  setSlug(event: Event): void {
    this.slugTouched = true;
    this.slug.set(this.text(event));
  }

  async create(): Promise<void> {
    this.busy.set('create');
    this.createErrors.set({});
    try {
      await this.world.create({ folder: this.folder().trim(), slug: this.slug().trim(), name: this.name().trim() });
      this.name.set('');
      this.slug.set('');
      this.folder.set('');
      this.slugTouched = false;
    } catch (err) {
      const e = toWorldError(err);
      const key = e.field && ['/folder', '/slug', '/name'].includes(e.field) ? e.field : 'general';
      this.createErrors.set({ [key]: e.field ? stripPointer(e.message, e.field) : e.message });
    } finally {
      this.busy.set(null);
    }
  }

  async open(): Promise<void> {
    this.busy.set('open');
    this.openError.set(null);
    try {
      await this.world.open(this.file().trim());
      this.file.set('');
    } catch (err) {
      this.openError.set(toWorldError(err).message);
    } finally {
      this.busy.set(null);
    }
  }

  async use(project: WorldProject): Promise<void> {
    this.actionError.set(null);
    await this.world.select(project.slug);
  }

  async askRemove(project: WorldProject): Promise<void> {
    const ok = await this.confirm.ask({
      title: this.w.removeTitle(project.name ?? project.slug),
      message: this.w.removeMessage(project.folder),
      confirmLabel: this.w.removeConfirm,
      cancelLabel: this.w.keep,
    });
    if (!ok) return;
    this.actionError.set(null);
    try {
      await this.world.remove(project.slug);
    } catch (err) {
      this.actionError.set(toWorldError(err).message);
    }
  }
}
