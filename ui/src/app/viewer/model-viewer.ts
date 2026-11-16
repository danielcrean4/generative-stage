import { afterNextRender, Component, computed, effect, ElementRef, inject, input, OnDestroy, signal, untracked, viewChild } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { formatSeconds, SPEEDS, statsLine } from './viewer-format';
import { ClipInfo, ModelInfo, PlaybackState, VIEWER_ENGINE, ViewerEngine } from './viewer-types';

/** Every word on this screen. */
const WORDS = {
  loading: 'Loading the 3D file…',
  unavailable: 'The 3D view is not available in this browser.',
  loadFailed: 'The 3D file could not be shown.',
  download: 'Download the file',
  reset: 'Reset view',
  wireframe: 'Wireframe',
  canvas: (name: string) => `3D view of ${name}. Drag to turn, scroll to zoom, right-drag to move.`,
  clips: 'Clips',
  clip: 'Clip',
  play: 'Play',
  pause: 'Pause',
  position: 'Position in the clip',
  loop: 'Loop',
  speed: 'Speed',
  speedOption: (x: number) => `${x}×`,
  length: (s: string) => `${s} s`,
};

/**
 * Shows a .glb the way it was exported: orbit, zoom and move, a reset, a wireframe switch, a line
 * of facts about the model and, when the file has animation clips, a player for them. three.js is
 * fetched on first use (see VIEWER_ENGINE), so a page that never shows a model never pays for it.
 */
@Component({
  selector: 'app-model-viewer',
  imports: [MatButtonModule],
  templateUrl: './model-viewer.html',
  styleUrl: './model-viewer.scss',
})
export class ModelViewer implements OnDestroy {
  readonly w = WORDS;
  readonly speeds = SPEEDS;
  /** Where to fetch the .glb from. */
  readonly url = input.required<string>();
  /** A short name for the model, used to describe the canvas. */
  readonly name = input('model');

  private readonly loadEngine = inject(VIEWER_ENGINE);
  private readonly canvas = viewChild.required<ElementRef<HTMLCanvasElement>>('canvas');

  readonly state = signal<'loading' | 'ready' | 'error'>('loading');
  readonly problem = signal<string | null>(null);
  readonly info = signal<ModelInfo | null>(null);
  readonly wireframe = signal(false);

  readonly clips = computed<ClipInfo[]>(() => this.info()?.clips ?? []);
  readonly clip = signal<string>('');
  readonly playing = signal(false);
  readonly time = signal(0);
  readonly loop = signal(true);
  readonly speed = signal(1);
  readonly stats = computed(() => (this.info() ? statsLine(this.info()!) : ''));
  readonly duration = computed(() => this.clips().find((c) => c.name === this.clip())?.duration ?? 0);

  private engine: ViewerEngine | null = null;
  private engineFailed = false;
  private ready = signal(false);
  private destroyed = false;

  constructor() {
    afterNextRender(() => void this.start());
    effect(() => {
      const url = this.url();
      if (this.ready()) untracked(() => void this.show(url));
    });
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    this.engine?.dispose();
    this.engine = null;
  }

  private async start(): Promise<void> {
    try {
      const factory = await this.loadEngine();
      if (this.destroyed) return;
      this.engine = factory(this.canvas().nativeElement);
      this.engine.onPlayback((s) => this.onPlayback(s));
      this.ready.set(true);
    } catch {
      this.engineFailed = true;
      this.fail(WORDS.unavailable);
    }
  }

  private async show(url: string): Promise<void> {
    if (!this.engine) return;
    this.state.set('loading');
    this.problem.set(null);
    this.playing.set(false);
    this.time.set(0);
    try {
      const info = await this.engine.load(url);
      if (this.destroyed || url !== this.url()) return;
      this.info.set(info);
      this.state.set('ready');
      this.engine.setWireframe(this.wireframe());
      this.engine.setSpeed(this.speed());
      this.engine.setLoop(this.loop());
      if (info.clips.length) this.chooseClip(info.clips[0].name);
    } catch (err) {
      if (this.destroyed || url !== this.url()) return;
      this.info.set(null);
      const detail = err instanceof Error && err.message ? ` ${err.message}` : '';
      this.fail(`${WORDS.loadFailed}${detail}`);
    }
  }

  private fail(message: string): void {
    this.state.set('error');
    this.problem.set(message);
  }

  private onPlayback(s: PlaybackState): void {
    this.time.set(s.time);
    this.playing.set(s.playing);
  }

  resetView(): void {
    this.engine?.resetView();
  }

  toggleWireframe(): void {
    this.wireframe.update((on) => !on);
    this.engine?.setWireframe(this.wireframe());
  }

  chooseClip(name: string): void {
    this.clip.set(name);
    this.engine?.selectClip(name);
  }

  togglePlay(): void {
    this.engine?.setPlaying(!this.playing());
    this.playing.set(!this.playing());
  }

  scrub(seconds: number): void {
    this.engine?.seek(seconds);
    this.time.set(seconds);
  }

  setLoop(on: boolean): void {
    this.loop.set(on);
    this.engine?.setLoop(on);
  }

  setSpeed(factor: number): void {
    this.speed.set(factor);
    this.engine?.setSpeed(factor);
  }

  seconds(s: number): string {
    return formatSeconds(s);
  }

  get unavailable(): boolean {
    return this.engineFailed;
  }
}
