import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AppRail, MENU_ITEMS } from './AppRail';
import { useJobsStore } from './jobsStore';

function renderRail(props: Parameters<typeof AppRail>[0] = {}, route = '/chart') {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <AppRail {...props} />
    </MemoryRouter>,
  );
}

describe('AppRail', () => {
  beforeEach(() => {
    useJobsStore.setState({ jobs: [] });
  });

  it('shows the seven menus in the order fixed by D1', () => {
    expect(MENU_ITEMS.map((item) => item.path)).toEqual([
      '/chart',
      '/research',
      '/test',
      '/alerts',
      '/bot',
      '/resources',
      '/ai',
    ]);
  });

  it('renders every menu plus settings and account', () => {
    renderRail();
    for (const label of [
      'Chart',
      'Research',
      'Test',
      'Alerts',
      'Trading bot',
      'Resources',
      'AI',
      'Settings',
      'Account',
    ]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
  });

  it('marks the current menu as active', () => {
    renderRail({}, '/research');
    const link = screen.getByTitle('Research');
    expect(link.className).toMatch(/active/);
    expect(screen.getByTitle('Chart').className).not.toMatch(/active/);
  });

  it('opens the jobs tray when the ring is clicked', async () => {
    const onOpenJobs = vi.fn();
    renderRail({ onOpenJobs });

    await userEvent.click(screen.getByRole('button', { name: 'Jobs' }));
    expect(onOpenJobs).toHaveBeenCalledTimes(1);
  });

  it('opens the alerts popover when the bell is clicked', async () => {
    const onOpenAlerts = vi.fn();
    renderRail({ onOpenAlerts });

    await userEvent.click(screen.getByRole('button', { name: 'Active alerts' }));
    expect(onOpenAlerts).toHaveBeenCalledTimes(1);
  });

  it('shows a badge only when alerts are active', () => {
    const { rerender } = renderRail({ activeAlertCount: 0 });
    expect(screen.queryByText('3')).not.toBeInTheDocument();

    rerender(
      <MemoryRouter initialEntries={['/chart']}>
        <AppRail activeAlertCount={3} />
      </MemoryRouter>,
    );
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('shows the queued-job count on the ring', () => {
    useJobsStore.setState({
      jobs: [
        { id: 'a', title: 'Discover', state: 'running', progress: 61 },
        { id: 'b', title: 'Backtest', state: 'queued', progress: 0 },
        { id: 'c', title: 'Walk-forward', state: 'queued', progress: 0 },
      ],
    });
    renderRail();

    expect(screen.getByText('61')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });
});
