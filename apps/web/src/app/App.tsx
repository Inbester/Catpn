/**
 * Root component: recovers the session, then renders either the shell or the
 * sign-in page.
 */

import { useEffect } from 'react';
import { RouterProvider, createBrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { onSessionExpired } from '@/lib/api/client';
import { useAuthStore } from '@/lib/auth/store';
import { startAutosave } from '@/lib/autosave/store';
import { applyLocale, isSupportedLocale } from '@/i18n';
import { applyTheme } from '@/lib/theme';
import { LoginPage } from '@/features/auth/LoginPage';
import { routes } from './routes';

const router = createBrowserRouter(routes);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function LoadingScreen() {
  return <div style={{ height: '100vh', background: 'var(--bg)' }} />;
}

export function App() {
  const status = useAuthStore((state) => state.status);
  const user = useAuthStore((state) => state.user);
  const bootstrap = useAuthStore((state) => state.bootstrap);
  const clearSession = useAuthStore((state) => state.clearSession);

  useEffect(() => {
    void bootstrap();
    return onSessionExpired(clearSession);
  }, [bootstrap, clearSession]);

  // Apply the signed-in user's stored preferences.
  useEffect(() => {
    if (!user) return;
    applyTheme(user.theme);
    if (isSupportedLocale(user.locale)) applyLocale(user.locale);
  }, [user]);

  // Autosave runs only while signed in; there is nothing to sync otherwise.
  useEffect(() => {
    if (status !== 'authenticated') return undefined;
    return startAutosave();
  }, [status]);

  if (status === 'unknown') return <LoadingScreen />;

  return (
    <QueryClientProvider client={queryClient}>
      {status === 'authenticated' ? <RouterProvider router={router} /> : <LoginPage />}
    </QueryClientProvider>
  );
}
