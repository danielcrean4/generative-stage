import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ModelViewer } from './model-viewer';
import { ModelInfo, PlaybackState, VIEWER_ENGINE, ViewerEngine } from './viewer-types';

const PLAIN: ModelInfo = { triangles: 12, vertices: 24, size: [1, 1, 1], materials: ['wood'], clips: [] };
const RIGGED: ModelInfo = { ...PLAIN, clips: [{ name: 'idle', duration: 2 }, { name: 'walk', duration: 0.6 }] };

/** An engine that only records what it is asked, so the viewer can be tested without WebGL. */
class FakeEngine implements ViewerEngine {
  calls: string[] = [];
  listener: ((s: PlaybackState) => void) | null = null;
  loads: string[] = [];
  constructor(private readonly result: () => Promise<ModelInfo>) {}
  load(url: string): Promise<ModelInfo> {
    this.loads.push(url);
    return this.result();
  }
  resetView(): void { this.calls.push('reset'); }
  setWireframe(on: boolean): void { this.calls.push(`wireframe:${on}`); }
  selectClip(name: string): void { this.calls.push(`clip:${name}`); }
  setPlaying(on: boolean): void { this.calls.push(`playing:${on}`); }
  seek(s: number): void { this.calls.push(`seek:${s}`); }
  setSpeed(x: number): void { this.calls.push(`speed:${x}`); }
  setLoop(on: boolean): void { this.calls.push(`loop:${on}`); }
  onPlayback(l: (s: PlaybackState) => void): void { this.listener = l; }
  dispose(): void { this.calls.push('dispose'); }
}

@Component({ imports: [ModelViewer], template: '<app-model-viewer [url]="url()" name="Bench" />' })
class Host {
  url = signal('/a.glb');
}

describe('ModelViewer', () => {
  let engine: FakeEngine;
  let fixture: ComponentFixture<Host>;

  async function setup(result: () => Promise<ModelInfo>, engineLoad?: () => Promise<never>) {
    engine = new FakeEngine(result);
    await TestBed.configureTestingModule({
      imports: [Host],
      providers: [{ provide: VIEWER_ENGINE, useValue: engineLoad ?? (async () => () => engine) }],
    }).compileComponents();
    fixture = TestBed.createComponent(Host);
    fixture.detectChanges();
    await vi.waitFor(() => expect(engine.loads.length || fixture.nativeElement.querySelector('[data-state="error"]')).toBeTruthy());
    await fixture.whenStable();
    fixture.detectChanges();
  }

  const el = (id: string) => fixture.nativeElement.querySelector(`[data-testid="${id}"]`) as HTMLElement | null;
  const action = (name: string) => fixture.nativeElement.querySelector(`[data-action="${name}"]`) as HTMLButtonElement;

  it('says it is loading until the file is read', async () => {
    let finish!: (i: ModelInfo) => void;
    await setup(() => new Promise((r) => (finish = r)));
    expect(el('viewer-loading')).toBeTruthy();
    expect(el('viewer-stats')).toBeNull();
    finish(PLAIN);
    await fixture.whenStable();
    fixture.detectChanges();
    expect(el('viewer-loading')).toBeNull();
    expect(el('viewer-stats')!.textContent).toContain('12 triangles, 24 vertices');
    expect(el('clip-player')).toBeNull();
  });

  it('asks the engine for the url it was given, and again when the url changes', async () => {
    await setup(async () => PLAIN);
    expect(engine.loads).toEqual(['/a.glb']);
    fixture.componentInstance.url.set('/b.glb');
    fixture.detectChanges();
    await vi.waitFor(() => expect(engine.loads).toEqual(['/a.glb', '/b.glb']));
  });

  it('shows a plain message and a download link when the file cannot be read', async () => {
    await setup(async () => { throw new Error('Unexpected token'); });
    const box = el('viewer-error')!;
    expect(box.textContent).toContain('The 3D file could not be shown.');
    expect(box.querySelector('a[download]')!.getAttribute('href')).toBe('/a.glb');
    expect(fixture.nativeElement.querySelector('.bar')).toBeNull();
  });

  it('says so when there is no WebGL', async () => {
    await setup(async () => PLAIN, async () => { throw new Error('no webgl'); });
    expect(el('viewer-error')!.textContent).toContain('not available in this browser');
    expect(el('viewer-error')!.querySelector('a')).toBeNull();
  });

  it('resets the view and toggles the wireframe', async () => {
    await setup(async () => PLAIN);
    action('reset-view').click();
    action('wireframe').click();
    fixture.detectChanges();
    expect(engine.calls).toContain('reset');
    expect(engine.calls).toContain('wireframe:true');
    expect(action('wireframe').getAttribute('aria-pressed')).toBe('true');
    action('wireframe').click();
    expect(engine.calls.at(-1)).toBe('wireframe:false');
  });

  describe('with clips', () => {
    beforeEach(() => setup(async () => RIGGED));

    it('lists the clips and selects the first, paused', () => {
      const options = [...fixture.nativeElement.querySelectorAll('[data-testid="clip-select"] option')].map((o) => (o as HTMLElement).textContent!.trim());
      expect(options).toEqual(['idle (2.00 s)', 'walk (0.60 s)']);
      expect(engine.calls).toContain('clip:idle');
      expect(action('play-clip').textContent).toContain('Play');
      expect(el('clip-time')!.textContent).toContain('0.00 / 2.00');
    });

    it('plays and pauses', () => {
      action('play-clip').click();
      fixture.detectChanges();
      expect(engine.calls.at(-1)).toBe('playing:true');
      expect(action('play-clip').textContent).toContain('Pause');
      action('play-clip').click();
      expect(engine.calls.at(-1)).toBe('playing:false');
    });

    it('follows the engine clock and scrubs', () => {
      engine.listener!({ time: 1.25, playing: true });
      fixture.detectChanges();
      expect(el('clip-time')!.textContent).toContain('1.25 / 2.00');
      const scrub = el('clip-scrub') as HTMLInputElement;
      scrub.value = '0.5';
      scrub.dispatchEvent(new Event('input'));
      expect(engine.calls.at(-1)).toBe('seek:0.5');
    });

    it('changes clip, loop and speed', () => {
      const select = el('clip-select') as HTMLSelectElement;
      select.value = 'walk';
      select.dispatchEvent(new Event('change'));
      expect(engine.calls.at(-1)).toBe('clip:walk');
      fixture.detectChanges();
      expect(el('clip-time')!.textContent).toContain('/ 0.60');
      const loop = el('clip-loop') as HTMLInputElement;
      loop.checked = false;
      loop.dispatchEvent(new Event('change'));
      expect(engine.calls.at(-1)).toBe('loop:false');
      const speed = el('clip-speed') as HTMLSelectElement;
      speed.value = '0.5';
      speed.dispatchEvent(new Event('change'));
      expect(engine.calls.at(-1)).toBe('speed:0.5');
    });
  });

  it('lets go of the engine when it goes away', async () => {
    await setup(async () => PLAIN);
    fixture.destroy();
    expect(engine.calls).toContain('dispose');
  });
});
