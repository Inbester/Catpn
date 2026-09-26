/**
 * The selected Setup, shared by every menu header.
 *
 * SPEC §0 puts a Setup picker in Test, Alerts and Bot. They must agree:
 * picking a Setup in one and finding another still selected elsewhere would
 * mean two menus acting on different rules while showing the same name.
 */

import { create } from 'zustand';

import * as setupsApi from './api';
import type { Setup } from './types';

const LAST_SETUP_KEY = 'quanta.setup.selected';

interface SetupsState {
  setups: Setup[];
  selectedId: string | null;
  loaded: boolean;

  load: () => Promise<void>;
  select: (id: string | null) => void;
  /** Take a freshly created or updated Setup into the list and select it. */
  adopt: (setup: Setup) => void;
}

function remember(id: string | null): void {
  try {
    if (id === null) localStorage.removeItem(LAST_SETUP_KEY);
    else localStorage.setItem(LAST_SETUP_KEY, id);
  } catch {
    // Private browsing denies storage; the selection just will not persist.
  }
}

function recall(): string | null {
  try {
    return localStorage.getItem(LAST_SETUP_KEY);
  } catch {
    return null;
  }
}

export const useSetupsStore = create<SetupsState>((set, get) => ({
  setups: [],
  selectedId: null,
  loaded: false,

  load: async () => {
    const setups = await setupsApi.listSetups();
    // Only keep a remembered selection that still exists — a Setup can be
    // archived from another tab or another device.
    const remembered = get().selectedId ?? recall();
    const selectedId = setups.some((setup) => setup.id === remembered) ? remembered : null;
    set({ setups, selectedId, loaded: true });
  },

  select: (id) => {
    remember(id);
    set({ selectedId: id });
  },

  adopt: (setup) => {
    remember(setup.id);
    set((state) => ({
      setups: [setup, ...state.setups.filter((existing) => existing.id !== setup.id)],
      selectedId: setup.id,
      loaded: true,
    }));
  },
}));

/** The selected Setup itself, or null. */
export function useSelectedSetup(): Setup | null {
  return useSetupsStore(
    (state) => state.setups.find((setup) => setup.id === state.selectedId) ?? null,
  );
}
