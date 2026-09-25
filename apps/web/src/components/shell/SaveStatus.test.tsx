import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { useAutosaveStore } from '@/lib/autosave/store';
import { SaveStatus } from './SaveStatus';

describe('SaveStatus', () => {
  beforeEach(() => {
    useAutosaveStore.setState({
      status: 'saved',
      pendingCount: 0,
      lastSavedAt: null,
      lastError: null,
    });
  });

  it('shows "Saved" when everything is synced', () => {
    render(<SaveStatus />);
    expect(screen.getByRole('status')).toHaveTextContent('Saved');
  });

  it('shows "Saving…" mid-flight', () => {
    useAutosaveStore.setState({ status: 'saving' });
    render(<SaveStatus />);
    expect(screen.getByRole('status')).toHaveTextContent('Saving');
  });

  it('shows "Offline" when the network is gone', () => {
    useAutosaveStore.setState({ status: 'offline' });
    render(<SaveStatus />);
    expect(screen.getByRole('status')).toHaveTextContent('Offline');
  });

  it('reports how many changes are still waiting', () => {
    useAutosaveStore.setState({ status: 'offline', pendingCount: 3 });
    render(<SaveStatus />);
    expect(screen.getByRole('status')).toHaveTextContent('3 changes waiting to sync');
  });

  it('hides the pending count once saved', () => {
    useAutosaveStore.setState({ status: 'saved', pendingCount: 0 });
    render(<SaveStatus />);
    expect(screen.getByRole('status')).not.toHaveTextContent('waiting to sync');
  });

  it('surfaces the failure reason as a tooltip', () => {
    useAutosaveStore.setState({ status: 'error', lastError: 'Internal server error.' });
    render(<SaveStatus />);
    expect(screen.getByRole('status')).toHaveAttribute('title', 'Internal server error.');
  });
});
