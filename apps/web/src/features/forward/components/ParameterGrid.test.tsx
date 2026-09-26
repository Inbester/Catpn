import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { ParameterGrid } from './ParameterGrid';
import { defaultRanges, type ParamRange } from '../lib/grid';

/** The grid is controlled, so editing it needs a parent that holds state. */
function Harness({ params }: { params: Record<string, number> }) {
  const [ranges, setRanges] = useState<Record<string, ParamRange>>(() => defaultRanges(params));
  return <ParameterGrid params={params} ranges={ranges} onChange={setRanges} />;
}

describe('ParameterGrid', () => {
  it('starts every parameter fixed, so opening the tab adds no work', () => {
    const ranges = defaultRanges({ fast: 20, slow: 50 });
    render(<ParameterGrid params={{ fast: 20, slow: 50 }} ranges={ranges} onChange={vi.fn()} />);

    expect(screen.getAllByText('fixed')).toHaveLength(2);
    expect(screen.getByText(/Every parameter is fixed/)).toBeInTheDocument();
  });

  it('says there is nothing to sweep when the strategy has no parameters', () => {
    render(<ParameterGrid params={{}} ranges={{}} onChange={vi.fn()} />);
    expect(screen.getByText(/no parameters, so there is nothing to sweep/)).toBeInTheDocument();
  });

  it('counts the combinations a sweep would run per window', () => {
    render(
      <ParameterGrid
        params={{ fast: 10, slow: 50 }}
        ranges={{
          fast: { from: 10, to: 20, step: 5 },
          slow: { from: 50, to: 80, step: 10 },
        }}
        onChange={vi.fn()}
      />,
    );

    // 3 fast values × 4 slow values.
    expect(screen.getByText('12 combinations')).toBeInTheDocument();
  });

  it('flags a range that covers nothing instead of running an empty sweep', () => {
    render(
      <ParameterGrid
        params={{ fast: 10 }}
        ranges={{ fast: { from: 30, to: 10, step: 5 } }}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText('no values')).toBeInTheDocument();
    expect(screen.getByText(/covers no values/)).toBeInTheDocument();
  });

  it('reports a grid past the interactive limit rather than sending it', () => {
    render(
      <ParameterGrid
        params={{ a: 1, b: 1 }}
        ranges={{ a: { from: 1, to: 30, step: 1 }, b: { from: 1, to: 30, step: 1 } }}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText('900 combinations')).toBeInTheDocument();
    expect(screen.getByText(/over the 400 an interactive run allows/)).toBeInTheDocument();
  });

  it('turns a fixed parameter into a sweep when its upper bound moves', async () => {
    const user = userEvent.setup();
    render(<Harness params={{ fast: 20 }} />);

    expect(screen.getByText('fixed')).toBeInTheDocument();

    await user.clear(screen.getByLabelText('fast to'));
    await user.type(screen.getByLabelText('fast to'), '40');

    // Step defaults to 5 for a value of 20, so 20..40 is five values.
    expect(screen.getByLabelText('fast from')).toHaveValue(20);
    expect(screen.getByLabelText('fast step')).toHaveValue(5);
    expect(screen.getByText(/^5 · 20, 25, …, 40$/)).toBeInTheDocument();
    expect(screen.getByText('5 combinations')).toBeInTheDocument();
  });
});
