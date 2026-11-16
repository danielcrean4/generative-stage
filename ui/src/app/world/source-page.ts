import { Component, effect, inject, signal, untracked } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { combineLatest, firstValueFrom, map } from 'rxjs';
import { typeWord } from './prompt-parts';
import { toWorldError, WorldApi } from './world-api';
import { formatTime } from './world-format';
import { WorldGate } from './world-gate';
import { SourcePage as SourceData, SourceType } from './world-models';
import { WorldProjectService } from './world-project.service';

/** Every word on this screen. */
const WORDS = {
  all: 'All sources',
  loading: 'Loading…',
  loadFailed: 'Could not open this source:',
  lives: 'Where it lives',
  readOnly: 'This file belongs to the tool, not to this project, so it is read-only here. To change it, edit the file in the tool\'s repository; the next run reads the new words.',
  words: 'Its words',
  from: (id: string) => `from ${id}`,
  extends: 'Builds on',
  extendsHelp: 'Words not set here come from these style packs, nearest first.',
  pipelines: 'Pipelines that use it',
  noPipelines: 'No offered pipeline uses it.',
  readBy: 'Runs that read it',
  readByHelp: 'Runs attached to records in this project, newest first.',
  noReaders: 'No run in this project has read it yet.',
  older: 'read an older version',
  file: 'The whole file',
  open: 'Open the run',
};

/**
 * One shared source of prompt text: a style pack, a motif or a contract. It shows the file's words and where the file lives,
 * the pipelines that use it and the runs of this project that read it, so "where did this text come from" can be answered
 * from either end. The files belong to the tool, so the page is read-only.
 */
@Component({
  selector: 'app-source-page',
  imports: [RouterLink, WorldGate],
  templateUrl: './source-page.html',
  styleUrl: './source-page.scss',
})
export class SourcePage {
  readonly w = WORDS;
  readonly world = inject(WorldProjectService);
  private readonly api = inject(WorldApi);
  private readonly route = inject(ActivatedRoute);

  private readonly params = toSignal(
    combineLatest([this.route.paramMap]).pipe(map(([p]) => ({ type: p.get('type'), id: p.get('id') }))),
    { initialValue: { type: null as string | null, id: null as string | null } },
  );

  readonly page = signal<SourceData | null>(null);
  readonly error = signal<string | null>(null);
  readonly word = typeWord;

  constructor() {
    effect(() => {
      const slug = this.world.slug();
      const { type, id } = this.params();
      untracked(() => {
        this.page.set(null);
        this.error.set(null);
        if (slug && type && id) void this.load(slug, type as SourceType, id);
      });
    });
  }

  private async load(slug: string, type: SourceType, id: string): Promise<void> {
    try {
      this.page.set(await firstValueFrom(this.api.source(slug, type, id)));
    } catch (err) {
      this.error.set(toWorldError(err).message);
    }
  }

  when(iso: string | null): string {
    return iso ? formatTime(iso) : '';
  }

  json(value: unknown): string {
    return JSON.stringify(value, null, 2);
  }
}
