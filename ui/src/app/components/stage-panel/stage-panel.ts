import { Component, DestroyRef, computed, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RunFile, RunViewApi, StageDetail } from '../../run-view-api';
import { ModelViewer } from '../../viewer/model-viewer';
import {
  KeyValueRow,
  fileKind,
  formatSize,
  measureRows,
  plural,
  recipeRows,
  verdictLabel,
  verdictOf,
} from '../../run-view-format';

interface OpenedText {
  name: string;
  loading: boolean;
  text: string | null;
  error: string | null;
}

/** One step of an attempt: what it was asked, what it produced and how its gates judged it. */
@Component({
  selector: 'app-stage-panel',
  imports: [ModelViewer],
  styleUrl: './stage-panel.scss',
  templateUrl: './stage-panel.html',
})
export class StagePanel {
  private readonly api = inject(RunViewApi);
  private readonly destroyRef = inject(DestroyRef);

  readonly stage = input.required<StageDetail>();
  readonly index = input.required<number>();

  readonly recipe = computed<KeyValueRow[]>(() => recipeRows(this.stage().recipe));
  /** Top-level files show inline; files inside a try folder are listed as links. */
  readonly mainFiles = computed(() => this.stage().files.filter((f) => !f.name.includes('/')));
  readonly nestedFiles = computed(() => this.stage().files.filter((f) => f.name.includes('/')));
  readonly opened = signal<OpenedText | null>(null);

  readonly fileKind = fileKind;
  readonly formatSize = formatSize;
  readonly measureRows = measureRows;
  readonly verdictLabel = verdictLabel;
  readonly verdictOf = verdictOf;
  readonly plural = plural;

  alt(file: RunFile): string {
    return `${this.stage().stage} output ${file.name}`;
  }

  view(file: RunFile): void {
    this.opened.set({ name: file.name, loading: true, text: null, error: null });
    this.api
      .fileText(file.url)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (text) => this.opened.set({ name: file.name, loading: false, text, error: null }),
        error: () =>
          this.opened.set({
            name: file.name,
            loading: false,
            text: null,
            error: 'Could not load this file. The run view server may be down.',
          }),
      });
  }

  closeViewer(): void {
    this.opened.set(null);
  }
}
