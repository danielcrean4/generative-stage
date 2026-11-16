import { of, throwError } from 'rxjs';
import { GenerateData } from './generate-data';
import { WorldApi } from './world-api';
import { JobView, WorldApiError } from './world-models';

function view(status: 'queued' | 'running' | 'succeeded' | 'failed'): JobView {
  return { job: { id: 'j1', entity_id: 'e1', entity_revision: 1 }, candidates: [], runs: [{ id: 'r1', status, log_tail: '', steps: [] }] };
}

describe('GenerateData', () => {
  it('loads the pipelines for the kind and the adapters', async () => {
    const api = { pipelines: vi.fn(() => of([])), adapters: vi.fn(() => of([])) } as unknown as WorldApi;
    const data = new GenerateData(api, 'p', 'e1', 'prop', () => undefined);
    await data.load();
    expect(api.pipelines).toHaveBeenCalledWith('p', 'prop');
    expect(data.loaded()).toBe(true);
  });

  it('queues a run, polls it until it ends and calls back once', async () => {
    const states = [view('running'), view('succeeded')];
    const api = { startJob: vi.fn(() => of(view('queued'))), job: vi.fn(() => of(states.shift()!)) } as unknown as WorldApi;
    const finished = vi.fn();
    const data = new GenerateData(api, 'p', 'e1', 'prop', finished, 1);
    expect(await data.start({ pipeline: 'concept', prompt: 'x' })).toBeNull();
    expect(data.active()).toBe(true);
    await vi.waitFor(() => expect(finished).toHaveBeenCalledTimes(1));
    expect(data.run()?.status).toBe('succeeded');
    expect(data.active()).toBe(false);
    expect(api.job).toHaveBeenCalledTimes(2);
  });

  it('resolves the API message when the request is refused, and does not poll', async () => {
    const api = { startJob: vi.fn(() => throwError(() => new WorldApiError(422, 'invalid', '/choices/seed: expected a whole number', '/choices/seed'))) } as unknown as WorldApi;
    const data = new GenerateData(api, 'p', 'e1', 'prop', () => undefined, 1);
    expect(await data.start({ pipeline: 'prop', prompt: 'x' })).toBe('/choices/seed: expected a whole number');
    expect(data.job()).toBeNull();
    expect(data.starting()).toBe(false);
  });

  it('stops polling when told to', async () => {
    const api = { startJob: vi.fn(() => of(view('queued'))), job: vi.fn(() => of(view('running'))) } as unknown as WorldApi;
    const finished = vi.fn();
    const data = new GenerateData(api, 'p', 'e1', 'prop', finished, 1);
    await data.start({ pipeline: 'concept', prompt: 'x' });
    data.stop();
    await new Promise((r) => setTimeout(r, 20));
    expect(finished).not.toHaveBeenCalled();
  });
});
