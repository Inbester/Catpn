/**
 * Route table.
 *
 * Every menu from D1 has a route from phase 0 so the shell is complete and
 * navigable; the pages fill in on their spec'd phases (SPEC §8).
 */

import { Navigate, type RouteObject } from 'react-router-dom';

import { AppLayout } from '@/components/shell/AppLayout';
import { ChartPage } from '@/features/chart/ChartPage';
import { ResearchPage } from '@/features/research/ResearchPage';
import { SetupsPage } from '@/features/setups/SetupsPage';
import { TestPage } from '@/features/test/TestPage';
import { PhasePlaceholder } from '@/features/placeholder/PhasePlaceholder';

export const routes: RouteObject[] = [
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <Navigate to="/chart" replace /> },
      { path: 'chart', element: <ChartPage /> },
      { path: 'research', element: <ResearchPage /> },
      { path: 'test', element: <TestPage /> },
      // SPEC §3.2 puts the Setups overview inside Research, which is phase 4.
      // It has its own route until then: the picker in every menu header has
      // to lead somewhere, and Setups are a phase 3 deliverable.
      { path: 'setups', element: <SetupsPage /> },
      {
        path: 'alerts',
        element: <PhasePlaceholder titleKey="nav.alerts" icon="alerts" phase={5} />,
      },
      {
        path: 'bot',
        element: <PhasePlaceholder titleKey="nav.bot" icon="bot" phase={6} />,
      },
      {
        path: 'resources',
        element: <PhasePlaceholder titleKey="nav.resources" icon="resources" phase={4} />,
      },
      {
        path: 'ai',
        element: <PhasePlaceholder titleKey="nav.ai" icon="ai" phase={7} />,
      },
      {
        path: 'settings',
        element: <PhasePlaceholder titleKey="nav.settings" icon="settings" phase={1} />,
      },
      {
        path: 'account',
        element: <PhasePlaceholder titleKey="nav.account" icon="account" phase={1} />,
      },
      { path: '*', element: <Navigate to="/chart" replace /> },
    ],
  },
];
