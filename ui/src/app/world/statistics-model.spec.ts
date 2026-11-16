import { barPercent, busiestDay, duration, longestStage } from './statistics-model';
import { Statistics } from './world-models';

const stats = {
  runs: { total: 3, completed: 2, errored: 1, other: 0, seconds: 100 },
  by_day: [
    { day: '2026-11-05', completed: 2, errored: 0, other: 0 },
    { day: '2026-11-06', completed: 1, errored: 2, other: 1 },
  ],
  by_stage: [
    { stage: 'a', ran: 1, reused: 0, errored: 0, total_seconds: 90, average_seconds: 90, slowest_seconds: 90 },
    { stage: 'b', ran: 1, reused: 0, errored: 0, total_seconds: 10, average_seconds: 10, slowest_seconds: 10 },
  ],
  assets: { candidates: 0, choices: 0, chosen_slots: 0, entities: 0, entities_with_choice: 0 },
} satisfies Statistics;

describe('statistics model', () => {
  it('scales bars to the longest', () => {
    expect(barPercent(50, 100)).toBe(50);
    expect(barPercent(0, 100)).toBe(0);
    expect(barPercent(1, 1000)).toBe(2);
    expect(barPercent(5, 0)).toBe(0);
  });

  it('writes lengths of time briefly', () => {
    expect(duration(45)).toBe('45 s');
    expect(duration(150)).toBe('2.5 min');
    expect(duration(4320)).toBe('1.2 h');
  });

  it('finds the busiest day and the longest stage', () => {
    expect(busiestDay(stats)).toBe(4);
    expect(longestStage(stats)).toBe(90);
    expect(busiestDay({ ...stats, by_day: [] })).toBe(0);
  });
});
