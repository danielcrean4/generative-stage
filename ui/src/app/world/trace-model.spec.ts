import { firstToLookAt, formatSeconds, isChosen, shownFiles, slotsFor, stageOutcome, stageTitle } from './trace-model';
import { Choice, TraceFile, TraceStage } from './world-models';

function stage(over: Partial<TraceStage> = {}): TraceStage {
  return {
    id: 'concept', folder: 'concept', retry: 0, label: 'Concept', tool: 'concept', status: 'completed', error: null,
    reused: false, reused_from: null, seconds: 5, started: null, finished: null, times: null, seed: 1, key: null,
    adapter: {}, prompt: null, negative: null, prompt_parts: null, negative_parts: null, params: null, reads: null, inputs: [], gates: [], files: [], ...over,
  };
}

function file(name: string, kind: TraceFile['kind']): TraceFile {
  return { name, kind, media_type: null, size: 1, candidate: `attempts/a/s/${name}`, url: `/f/${name}` };
}

describe('trace model', () => {
  it('takes the worst gate outcome of a stage', () => {
    const gate = (outcome: 'pass' | 'review' | 'fail' | null) => ({ file: null, outcome, reasons: [], measures: [], limits: [] });
    expect(stageOutcome(stage())).toBeNull();
    expect(stageOutcome(stage({ gates: [gate('pass'), gate('review')] }))).toBe('review');
    expect(stageOutcome(stage({ gates: [gate('review'), gate('fail'), gate(null)] }))).toBe('fail');
  });

  it('writes durations the way a person reads them', () => {
    expect(formatSeconds(null)).toBeNull();
    expect(formatSeconds(0.4)).toBe('0 s');
    expect(formatSeconds(45)).toBe('45 s');
    expect(formatSeconds(125)).toBe('2 min 05 s');
    expect(formatSeconds(3780)).toBe('1 h 03 min');
  });

  it('names a retried stage', () => {
    expect(stageTitle(stage({ label: 'Shape' }))).toBe('Shape');
    expect(stageTitle(stage({ label: 'Shape', retry: 2 }))).toBe('Shape (retry 2)');
  });

  it('shows pictures and 3D files, not reports', () => {
    const s = stage({ files: [file('a.json', 'other'), file('a.png', 'image'), file('m.glb', 'model')] });
    expect(shownFiles(s).map((f) => f.name)).toEqual(['a.png', 'm.glb']);
  });

  it('offers slots by kind of file', () => {
    expect(slotsFor(file('a.png', 'image'))).toEqual(['main', 'icon']);
    expect(slotsFor(file('m.glb', 'model'))).toEqual(['mesh']);
    expect(slotsFor(file('a.json', 'other'))).toEqual([]);
  });

  it('knows which slot a file is chosen for', () => {
    const chosen = { main: { run_id: 'r1', candidate: 'attempts/a/s/a.png' } as Choice };
    expect(isChosen(file('a.png', 'image'), 'r1', chosen)).toBe('main');
    expect(isChosen(file('a.png', 'image'), 'r2', chosen)).toBeNull();
    expect(isChosen(file('b.png', 'image'), 'r1', chosen)).toBeNull();
  });

  it('opens on the stage that went wrong', () => {
    const fine = stage({ id: 'a' });
    const bad = stage({ id: 'b', status: 'errored' });
    const never = stage({ id: 'c', status: 'not_run' });
    expect(firstToLookAt([fine, bad, never])?.id).toBe('b');
    expect(firstToLookAt([fine, never])?.id).toBe('a');
    expect(firstToLookAt([])).toBeNull();
  });
});
