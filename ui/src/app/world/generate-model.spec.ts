import { adapterKinds, adapterOptions, choiceList, formFor, problems, promptFor, requestOf, statusWords } from './generate-model';
import { Adapter, Pipeline } from './world-models';

const prop: Pipeline = {
  id: 'prop',
  name: 'Props from a concept image',
  kind: 'prop',
  entity_kinds: ['prop'],
  stages: [
    { id: 'concept', label: 'Concept image', tool: 'concept', adapter_kind: 'image' },
    { id: 'matte', label: 'Find the subject', tool: 'matte', adapter_kind: null },
    { id: 'mesh', label: 'Image to mesh', tool: 'mesh', adapter_kind: 'image-to-mesh' },
  ],
  choices: {
    seed: { label: 'Seed', min: 0, max: 99, default: 1 },
    style: { label: 'Style', options: ['clay', 'vinyl_toy'], default: 'clay' },
  },
};

function adapter(id: string, kind: string, extra: Partial<Adapter> = {}): Adapter {
  return { id, kind, description: '', default: false, runnable: true, unmet: [], ...extra };
}

const adapters = [
  adapter('b-image', 'image'),
  adapter('standin-image', 'image', { default: true }),
  adapter('standin-mesh', 'image-to-mesh', { default: true }),
  adapter('big-mesh', 'image-to-mesh', { runnable: false, unmet: ['needs CUDA'] }),
];

describe('generate model', () => {
  it('lists the adapter kinds a pipeline runs, once each, and its choices in a fixed order', () => {
    expect(adapterKinds(prop)).toEqual(['image', 'image-to-mesh']);
    expect(choiceList(prop).map((c) => c.name)).toEqual(['style', 'seed']);
  });

  it('starts a form on the declared defaults with no adapter picked', () => {
    expect(formFor(prop, 'a key')).toEqual({ pipeline: 'prop', prompt: 'a key', adapters: {}, choices: { style: 'clay', seed: 1 } });
  });

  it('puts the default adapter first and says why one cannot run here', () => {
    expect(adapterOptions(adapters, 'image').map((o) => o.id)).toEqual(['standin-image', 'b-image']);
    const mesh = adapterOptions(adapters, 'image-to-mesh');
    expect(mesh[1].runnable).toBe(false);
    expect(mesh[1].label).toContain('cannot run here: needs CUDA');
  });

  it('makes a request with only the adapters picked for kinds the pipeline runs, and every declared choice', () => {
    const form = { ...formFor(prop, '  a key '), adapters: { image: 'b-image', rig: 'x', 'image-to-mesh': '' } };
    expect(requestOf(prop, form)).toEqual({ pipeline: 'prop', prompt: 'a key', adapters: { image: 'b-image' }, choices: { style: 'clay', seed: 1 } });
    expect(requestOf(prop, formFor(prop, 'a key')).adapters).toBeUndefined();
  });

  it('says what stops a run, in order', () => {
    const ok = formFor(prop, 'a key');
    expect(problems(prop, adapters, ok)).toEqual([]);
    expect(problems(null, adapters, ok)).toEqual(['Choose a pipeline.']);
    expect(problems(prop, adapters, { ...ok, prompt: ' ' })).toEqual(['Describe what to make.']);
    expect(problems(prop, adapters, { ...ok, choices: { style: 'marble', seed: 100 } })).toEqual([
      'Style: choose one of the options.',
      'Seed: enter a whole number from 0 to 99.',
    ]);
    expect(problems(prop, adapters, { ...ok, choices: { ...ok.choices, seed: Number.NaN } })).toHaveLength(1);
    expect(problems(prop, adapters, { ...ok, adapters: { 'image-to-mesh': 'big-mesh' } })).toEqual(['3D model: big-mesh cannot run here (needs CUDA).']);
    expect(problems(prop, [], ok)).toEqual(['Image model: this computer has none set up.', '3D model: this computer has none set up.']);
  });

  it('treats the picture to start from as optional: no default, no prompt needed once one is picked', () => {
    const mesh: Pipeline = {
      ...prop,
      choices: { ...prop.choices, start_image: { label: 'Make it from the image chosen as', slots: ['main', 'icon'] }, hair_colour: { label: 'Hair colour', options: ['#111111', '#222222'] } },
    };
    expect(choiceList(mesh).map((c) => c.name)).toEqual(['style', 'hair_colour', 'seed', 'start_image']);
    const form = formFor(mesh, '');
    expect(form.choices).toEqual({ style: 'clay', seed: 1 });
    expect(problems(mesh, adapters, form)).toEqual(['Describe what to make.']);
    const picked = { ...form, choices: { ...form.choices, start_image: 'main' } };
    expect(problems(mesh, adapters, { ...picked, choices: { ...picked.choices, hair_colour: '#999999' } })).toEqual(['Hair colour: choose one of the options.']);
    expect(problems(mesh, adapters, picked)).toEqual([]);
    expect(problems(mesh, adapters, { ...picked, choices: { ...picked.choices, start_image: 'mesh' } })).toEqual(['Make it from the image chosen as: choose one of the pictures.']);
    expect(requestOf(mesh, picked).choices).toEqual({ style: 'clay', seed: 1, start_image: 'main' });
    expect(requestOf(mesh, { ...picked, choices: { ...picked.choices, start_image: '' } }).choices).not.toHaveProperty('start_image');
  });

  it('starts a prompt from the brief, else the title, and words the run states', () => {
    expect(promptFor('Key', ' A brass key. ')).toBe('A brass key.');
    expect(promptFor('Key', '')).toBe('Key');
    expect(promptFor('Key', undefined)).toBe('Key');
    expect(statusWords('queued')).toBe('Waiting to start');
  });
});
