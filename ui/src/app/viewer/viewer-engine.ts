import {
  AmbientLight,
  AnimationAction,
  AnimationMixer,
  Box3,
  Color,
  DirectionalLight,
  GridHelper,
  HemisphereLight,
  LoopOnce,
  LoopRepeat,
  Material,
  Mesh,
  Object3D,
  PerspectiveCamera,
  Scene,
  Timer,
  Vector3,
  WebGLRenderer,
} from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { ClipInfo, EngineFactory, ModelInfo, PlaybackState, ViewerEngine } from './viewer-types';

const BACKGROUND = 0xd7dadf;
const GRID_MAIN = 0x8b9099;
const GRID_SIDE = 0xb4b8bf;

/** Adds up what a loaded scene holds. Exported for the unit test. */
export function measure(root: Object3D): Omit<ModelInfo, 'clips'> {
  let triangles = 0;
  let vertices = 0;
  const materials = new Map<string, Material>();
  root.traverse((node) => {
    const mesh = node as Mesh;
    if (!mesh.isMesh) return;
    const position = mesh.geometry.getAttribute('position');
    const count = position ? position.count : 0;
    vertices += count;
    triangles += (mesh.geometry.index ? mesh.geometry.index.count : count) / 3;
    for (const m of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) materials.set(m.uuid, m);
  });
  const box = new Box3().setFromObject(root);
  const size = box.getSize(new Vector3());
  return { triangles: Math.round(triangles), vertices, size: [size.x, size.y, size.z], materials: [...materials.values()].map((m) => m.name || 'unnamed') };
}

class Engine implements ViewerEngine {
  private readonly renderer: WebGLRenderer;
  private readonly scene = new Scene();
  private readonly camera = new PerspectiveCamera(40, 1, 0.01, 1000);
  private readonly controls: OrbitControls;
  private readonly timer = new Timer();
  private readonly observer: ResizeObserver;
  private model: Object3D | null = null;
  private grid: GridHelper | null = null;
  private mixer: AnimationMixer | null = null;
  private clips: { info: ClipInfo; action: AnimationAction }[] = [];
  private active: AnimationAction | null = null;
  private playing = false;
  private wireframe = false;
  private speed = 1;
  private loop = true;
  private home = { position: new Vector3(2, 1.5, 3), target: new Vector3() };
  private listener: ((state: PlaybackState) => void) | null = null;
  private frame = 0;
  private dirty = true;
  private loadToken = 0;
  private disposed = false;

  constructor(private readonly canvas: HTMLCanvasElement) {
    this.renderer = new WebGLRenderer({ canvas, antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.scene.background = new Color(BACKGROUND);
    this.scene.add(new HemisphereLight(0xffffff, 0x8a8f98, 1.6));
    this.scene.add(new AmbientLight(0xffffff, 0.4));
    const key = new DirectionalLight(0xffffff, 2.2);
    key.position.set(3, 5, 4);
    this.scene.add(key);
    const fill = new DirectionalLight(0xffffff, 0.8);
    fill.position.set(-4, 2, -3);
    this.scene.add(fill);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = false;
    this.controls.addEventListener('change', () => (this.dirty = true));
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(canvas);
    this.resize();
    this.frame = requestAnimationFrame(() => this.tick());
  }

  async load(url: string): Promise<ModelInfo> {
    const token = ++this.loadToken;
    const gltf = await new GLTFLoader().loadAsync(url);
    if (this.disposed || token !== this.loadToken) throw new Error('Superseded by a newer load.');
    this.clear();
    const model = gltf.scene;
    this.scene.add(model);
    this.model = model;
    const info = measure(model);
    const box = new Box3().setFromObject(model);
    model.position.y -= box.min.y; // stand it on the ground
    const centre = box.getCenter(new Vector3());
    model.position.x -= centre.x;
    model.position.z -= centre.z;
    this.frameCamera(info.size);
    const extent = Math.max(info.size[0], info.size[2], 0.5) * 2.5;
    this.grid = new GridHelper(Math.ceil(extent), Math.ceil(extent) * 2, GRID_MAIN, GRID_SIDE);
    this.scene.add(this.grid);
    this.mixer = gltf.animations.length ? new AnimationMixer(model) : null;
    this.clips = gltf.animations.map((clip) => ({ info: { name: clip.name, duration: clip.duration }, action: this.mixer!.clipAction(clip) }));
    this.active = null;
    this.playing = false;
    this.applyWireframe();
    this.dirty = true;
    return { ...info, clips: this.clips.map((c) => c.info) };
  }

  resetView(): void {
    this.camera.position.copy(this.home.position);
    this.controls.target.copy(this.home.target);
    this.controls.update();
    this.dirty = true;
  }

  setWireframe(on: boolean): void {
    this.wireframe = on;
    this.applyWireframe();
  }

  selectClip(name: string): void {
    const found = this.clips.find((c) => c.info.name === name);
    if (!found) return;
    this.active?.stop();
    this.active = found.action;
    this.applyLoop();
    this.active.reset().play();
    this.active.paused = !this.playing;
    this.active.timeScale = this.speed;
    this.mixer?.update(0);
    this.report();
  }

  setPlaying(on: boolean): void {
    this.playing = on;
    if (!this.active) return;
    if (on && !this.loop && this.active.time >= this.active.getClip().duration) this.active.reset().play();
    this.active.paused = !on;
    this.timer.update();
    this.report();
  }

  seek(seconds: number): void {
    if (!this.active) return;
    this.active.time = Math.max(0, Math.min(seconds, this.active.getClip().duration));
    this.mixer?.update(0);
    this.dirty = true;
    this.report();
  }

  setSpeed(factor: number): void {
    this.speed = factor;
    if (this.active) this.active.timeScale = factor;
  }

  setLoop(on: boolean): void {
    this.loop = on;
    this.applyLoop();
  }

  onPlayback(listener: (state: PlaybackState) => void): void {
    this.listener = listener;
  }

  dispose(): void {
    this.disposed = true;
    cancelAnimationFrame(this.frame);
    this.observer.disconnect();
    this.controls.dispose();
    this.clear();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
  }

  private clear(): void {
    if (this.model) {
      this.scene.remove(this.model);
      this.model.traverse((node) => {
        const mesh = node as Mesh;
        if (!mesh.isMesh) return;
        mesh.geometry.dispose();
        for (const m of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) m.dispose();
      });
    }
    if (this.grid) {
      this.scene.remove(this.grid);
      this.grid.dispose();
    }
    this.mixer?.stopAllAction();
    this.model = this.grid = this.mixer = this.active = null;
    this.clips = [];
  }

  private applyWireframe(): void {
    this.model?.traverse((node) => {
      const mesh = node as Mesh;
      if (!mesh.isMesh) return;
      for (const m of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) (m as Material & { wireframe: boolean }).wireframe = this.wireframe;
    });
    this.dirty = true;
  }

  private applyLoop(): void {
    if (!this.active) return;
    this.active.setLoop(this.loop ? LoopRepeat : LoopOnce, Infinity);
    this.active.clampWhenFinished = true;
  }

  private frameCamera(size: [number, number, number]): void {
    const radius = Math.max(0.5 * Math.hypot(...size), 0.1);
    const distance = radius / Math.sin((this.camera.fov * Math.PI) / 360);
    const target = new Vector3(0, size[1] / 2, 0);
    this.home = { target, position: target.clone().add(new Vector3(0.6, 0.35, 1).normalize().multiplyScalar(distance * 1.05)) };
    this.camera.near = distance / 100;
    this.camera.far = distance * 100;
    this.camera.updateProjectionMatrix();
    this.controls.maxDistance = distance * 10;
    this.resetView();
  }

  private resize(): void {
    const width = this.canvas.clientWidth;
    const height = this.canvas.clientHeight;
    if (!width || !height) return;
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.dirty = true;
  }

  private report(): void {
    if (!this.listener) return;
    this.listener({ time: this.active?.time ?? 0, playing: this.playing && !(this.active?.paused ?? true) });
  }

  private tick(): void {
    if (this.disposed) return;
    this.frame = requestAnimationFrame(() => this.tick());
    this.timer.update();
    const delta = this.timer.getDelta();
    if (this.playing && this.mixer && this.active) {
      this.mixer.update(delta);
      this.dirty = true;
      const finished = !this.loop && this.active.time >= this.active.getClip().duration;
      if (finished) this.playing = false;
      this.report();
    }
    if (this.dirty) {
      this.dirty = false;
      this.renderer.render(this.scene, this.camera);
    }
  }
}

export const createEngine: EngineFactory = (canvas) => new Engine(canvas);
