import { AttemptDetail, StageDetail } from './run-view-api';

export function stage(overrides: Partial<StageDetail> & { stage: string }): StageDetail {
  return {
    recorded: true,
    cache_key: 'abc123',
    reused: false,
    status: null,
    seed: 7,
    seed_used: null,
    tries: null,
    recipe: { stage: overrides.stage, seed: 7, settings: { prompt: 'a test prompt', width: 512 } },
    gates: [],
    files: [],
    ...overrides,
  };
}

export function attempt(overrides: Partial<AttemptDetail> = {}): AttemptDetail {
  return {
    run_id: 'run-1',
    attempt_id: 'att-1',
    status: 'generated',
    error: null,
    started: '2026-11-11T02:08:34Z',
    finished: '2026-11-11T02:09:13Z',
    seed: 7,
    recipe: { stages: ['zeta', 'alpha'] },
    problem: null,
    stages: [],
    ...overrides,
  };
}
