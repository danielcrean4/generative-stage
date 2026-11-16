import { InjectionToken } from '@angular/core';

/** What a loaded 3D file contains, measured as exported. */
export interface ModelInfo {
  triangles: number;
  vertices: number;
  /** Bounding box size in the file's own units (metres for glTF): width, height, depth. */
  size: [number, number, number];
  /** One entry per material, by name. */
  materials: string[];
  clips: ClipInfo[];
}

export interface ClipInfo {
  name: string;
  /** Seconds. */
  duration: number;
}

/** Where the clip is, reported every frame while it moves. */
export interface PlaybackState {
  time: number;
  playing: boolean;
}

/** The part of the viewer that touches WebGL. Everything else in the viewer works against this. */
export interface ViewerEngine {
  load(url: string): Promise<ModelInfo>;
  resetView(): void;
  setWireframe(on: boolean): void;
  /** Selects a clip and shows its first frame; playback stays as it was. */
  selectClip(name: string): void;
  setPlaying(on: boolean): void;
  seek(seconds: number): void;
  setSpeed(factor: number): void;
  setLoop(on: boolean): void;
  onPlayback(listener: (state: PlaybackState) => void): void;
  dispose(): void;
}

export type EngineFactory = (canvas: HTMLCanvasElement) => ViewerEngine;

/**
 * How the viewer gets its engine. The default loads three.js on first use, as a separate chunk, so
 * pages that never show a 3D file do not download it. Tests provide a fake.
 */
export const VIEWER_ENGINE = new InjectionToken<() => Promise<EngineFactory>>('VIEWER_ENGINE', {
  providedIn: 'root',
  factory: () => async () => (await import('./viewer-engine')).createEngine,
});
