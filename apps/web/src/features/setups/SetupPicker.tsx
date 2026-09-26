/**
 * The Setup picker that sits in every menu header (SPEC §0).
 *
 * It shows what the menu is acting on — name, market and locked version —
 * because a menu that silently acts on "the current strategy" is how an
 * alert ends up firing on rules nobody tested.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';

import { Icon } from '@/components/Icon';
import { StageChips } from './components/StageChips';
import { useSetupsStore } from './lib/store';
import type { Setup } from './lib/types';
import styles from './SetupPicker.module.css';

function describe(setup: Setup): string {
  return (
    `${setup.symbol} · ${setup.interval} · ` +
    `${setup.margin_percent}% × ${setup.leverage}× · ${setup.strategy_version.slice(0, 8)}`
  );
}

function matches(setup: Setup, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return [setup.name, setup.symbol, setup.interval, setup.strategy_version].some((field) =>
    field.toLowerCase().includes(needle),
  );
}

export function SetupPicker() {
  const { t } = useTranslation();
  const { setups, selectedId, loaded, load, select } = useSetupsStore();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [anchor, setAnchor] = useState<{ left: number; top: number } | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);

  // The dropdown is a portal pinned to the trigger's viewport position: menu
  // headers scroll horizontally, and an absolutely positioned panel inside
  // one is clipped by that scroll container.
  const place = useCallback(() => {
    const rect = trigger.current?.getBoundingClientRect();
    if (rect) setAnchor({ left: rect.left, top: rect.bottom + 8 });
  }, []);

  useEffect(() => {
    if (!loaded) {
      void load().catch(() => {
        // The picker is not worth blocking a menu over; it stays empty.
      });
    }
  }, [loaded, load]);

  useEffect(() => {
    if (!open) return;
    place();

    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!root.current?.contains(target) && !panel.current?.contains(target)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    window.addEventListener('resize', place);
    // Capture, so a scroll in any ancestor moves the panel with the trigger.
    window.addEventListener('scroll', place, true);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('resize', place);
      window.removeEventListener('scroll', place, true);
    };
  }, [open, place]);

  const selected = setups.find((setup) => setup.id === selectedId) ?? null;
  const visible = useMemo(() => setups.filter((setup) => matches(setup, query)), [setups, query]);

  return (
    <div className={styles.root} ref={root}>
      <button
        type="button"
        ref={trigger}
        className={styles.trigger}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => {
          setOpen((current) => !current);
        }}
      >
        {selected ? (
          <>
            <span className={styles.swatch} style={{ background: selected.color }} />
            <span className={styles.triggerName}>{selected.name}</span>
            <span className={styles.triggerMeta}>{describe(selected)}</span>
          </>
        ) : (
          <span className={styles.triggerName}>{t('setups.picker.none')}</span>
        )}
        <Icon name="chevronDown" size={12} />
      </button>

      {open && anchor
        ? createPortal(
            <div
              className={styles.dropdown}
              role="listbox"
              ref={panel}
              style={{ left: anchor.left, top: anchor.top }}
            >
              <div className={styles.search}>
                <Icon name="search" size={14} />
                <input
                  className={styles.searchInput}
                  placeholder={t('setups.picker.search')}
                  value={query}
                  autoFocus
                  onChange={(event) => {
                    setQuery(event.target.value);
                  }}
                />
              </div>

              <div className={styles.rows}>
                {visible.map((setup) => (
                  <button
                    key={setup.id}
                    type="button"
                    role="option"
                    aria-selected={setup.id === selectedId}
                    className={`${styles.row} ${setup.id === selectedId ? styles.rowActive : ''}`}
                    onClick={() => {
                      select(setup.id);
                      setOpen(false);
                    }}
                  >
                    <span className={styles.swatch} style={{ background: setup.color }} />
                    <span className={styles.rowText}>
                      <span className={styles.rowName}>{setup.name}</span>
                      <span className={styles.rowMeta}>{describe(setup)}</span>
                    </span>
                    <StageChips setup={setup} />
                  </button>
                ))}

                {visible.length === 0 ? (
                  <p className={styles.empty}>
                    {setups.length === 0
                      ? 'No setups yet. Run a backtest and save the result as one.'
                      : `Nothing matches “${query}”.`}
                  </p>
                ) : null}
              </div>

              <div className={styles.footer}>
                {selected ? (
                  <button
                    type="button"
                    className={styles.clear}
                    onClick={() => {
                      select(null);
                      setOpen(false);
                    }}
                  >
                    {t('setups.picker.clear')}
                  </button>
                ) : (
                  <span />
                )}
                <Link
                  to="/setups"
                  className={styles.manage}
                  onClick={() => {
                    setOpen(false);
                  }}
                >
                  {t('setups.picker.manage')}
                </Link>
              </div>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
