import { verdictLabel, verdictOf } from './run-view-format';

describe('gate verdicts', () => {
  it('reads pass and fail from `passed` when the report has no verdict word', () => {
    expect(verdictOf(true)).toBe('pass');
    expect(verdictOf(false)).toBe('fail');
    expect(verdictOf(null)).toBe('none');
  });

  it('shows a gate v2 review as its own verdict, not as a failure', () => {
    expect(verdictOf(false, 'review')).toBe('review');
    expect(verdictLabel(false, 'review')).toContain('review');
    expect(verdictOf(false, 'fail')).toBe('fail');
    expect(verdictOf(true, 'pass')).toBe('pass');
  });
});
