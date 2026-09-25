/** Add an indicator to the chart (SPEC §3.1). */

import { useEffect } from 'react';

import { Icon } from '@/components/Icon';
import { INDICATOR_LIST, type IndicatorId } from '../lib/indicatorRegistry';
import styles from './IndicatorsDialog.module.css';

export interface IndicatorsDialogProps {
  onAdd: (id: IndicatorId) => void;
  onClose: () => void;
}

export function IndicatorsDialog({ onAdd, onClose }: IndicatorsDialogProps) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [onClose]);

  const overlays = INDICATOR_LIST.filter((definition) => definition.overlay);
  const panes = INDICATOR_LIST.filter((definition) => !definition.overlay);

  return (
    <div
      className={styles.backdrop}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className={styles.dialog} role="dialog" aria-label="Indicators">
        <div className={styles.header}>
          <span className={styles.title}>Indicators</span>
          <button type="button" className={styles.close} onClick={onClose} aria-label="Close">
            <Icon name="close" size={16} />
          </button>
        </div>

        <div className={styles.body}>
          <div className={styles.section}>On the price chart</div>
          {overlays.map((definition) => (
            <button
              key={definition.id}
              type="button"
              className={styles.item}
              onClick={() => {
                onAdd(definition.id);
              }}
            >
              <span>
                <span className={styles.name}>{definition.name}</span>
                <span className={styles.meta}> · {definition.label(definition.defaults)}</span>
              </span>
              <Icon name="plus" size={16} className={styles.add} />
            </button>
          ))}

          <div className={styles.section}>In their own pane</div>
          {panes.map((definition) => (
            <button
              key={definition.id}
              type="button"
              className={styles.item}
              onClick={() => {
                onAdd(definition.id);
              }}
            >
              <span>
                <span className={styles.name}>{definition.name}</span>
                <span className={styles.meta}> · {definition.label(definition.defaults)}</span>
              </span>
              <Icon name="plus" size={16} className={styles.add} />
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
