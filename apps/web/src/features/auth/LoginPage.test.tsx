import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api/client';
import { useAuthStore } from '@/lib/auth/store';
import { LoginPage } from './LoginPage';

describe('LoginPage', () => {
  beforeEach(() => {
    useAuthStore.setState({ status: 'anonymous', user: null, mfaTicket: null });
    vi.restoreAllMocks();
  });

  it('signs in with an email and password', async () => {
    const login = vi.fn().mockResolvedValue('authenticated');
    useAuthStore.setState({ login });

    render(<LoginPage />);
    await userEvent.type(screen.getByLabelText('Email'), 'trader@example.com');
    await userEvent.type(screen.getByLabelText('Password'), 'Sunset-Harbour-42!');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(login).toHaveBeenCalledWith('trader@example.com', 'Sunset-Harbour-42!');
  });

  it('shows the server error message when sign-in fails', async () => {
    useAuthStore.setState({
      login: vi.fn().mockRejectedValue(new ApiError(401, 'Incorrect email or password.')),
    });

    render(<LoginPage />);
    await userEvent.type(screen.getByLabelText('Email'), 'trader@example.com');
    await userEvent.type(screen.getByLabelText('Password'), 'wrong');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect email or password.');
  });

  it('switches to the two-factor step when the account has 2FA', () => {
    useAuthStore.setState({ status: 'mfa-required', mfaTicket: 'ticket-1' });
    render(<LoginPage />);

    expect(screen.getByLabelText('Two-factor code')).toBeInTheDocument();
    // The password fields are gone at this point.
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument();
  });

  it('submits the two-factor code', async () => {
    const verifyMfa = vi.fn().mockResolvedValue(undefined);
    useAuthStore.setState({ status: 'mfa-required', mfaTicket: 'ticket-1', verifyMfa });

    render(<LoginPage />);
    await userEvent.type(screen.getByLabelText('Two-factor code'), '123456');
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }));

    expect(verifyMfa).toHaveBeenCalledWith('123456');
  });

  it('can switch to creating an account', async () => {
    render(<LoginPage />);
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }));

    expect(screen.getByLabelText('Name')).toBeInTheDocument();
    expect(screen.getByText(/At least 12 characters/)).toBeInTheDocument();
  });

  it('registers a new account', async () => {
    const register = vi.fn().mockResolvedValue(undefined);
    useAuthStore.setState({ register });

    render(<LoginPage />);
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }));
    await userEvent.type(screen.getByLabelText('Name'), 'Test Trader');
    await userEvent.type(screen.getByLabelText('Email'), 'new@example.com');
    await userEvent.type(screen.getByLabelText('Password'), 'Sunset-Harbour-42!');
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }));

    expect(register).toHaveBeenCalledWith('new@example.com', 'Test Trader', 'Sunset-Harbour-42!');
  });
});
