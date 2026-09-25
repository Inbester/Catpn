import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import '@/styles/global.css';
import '@/i18n';
import { App } from '@/app/App';
import { initTheme } from '@/lib/theme';

// Applied before the first paint so there is no flash of the wrong theme.
initTheme();

const container = document.getElementById('root');
if (!container) throw new Error('Root element #root is missing from index.html.');

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
