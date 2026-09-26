/**
 * Creating and editing an alert (SPEC §3.4).
 *
 * The preview is not decoration. A template is user-written text rendered
 * on a server and sent to a phone, and the only way to find a mistyped
 * variable is to look at the result — so the form shows what will be sent,
 * names any variable that will not fill in, and says plainly that the
 * disclaimer cannot be removed.
 */

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Icon } from '@/components/Icon';
import { ApiError } from '@/lib/api/client';
import type { Setup } from '@/features/setups/lib/types';
import * as alertsApi from '../lib/api';
import {
  ALERT_SOURCES,
  REPEAT_MODES,
  type Alert,
  type AlertSource,
  type Destination,
  type DestinationKind,
  type RepeatMode,
} from '../lib/types';
import styles from './alerts.module.css';

const DESTINATION_KINDS: DestinationKind[] = ['telegram', 'web_push', 'webhook', 'email'];

/** A condition value as form text. Conditions are free-form JSON, so a
 *  value of an unexpected shape becomes the fallback rather than
 *  "[object Object]" in an input the user then saves back. */
function text(value: unknown, fallback = ''): string {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return fallback;
}

export interface AlertFormProps {
  alert: Alert | null;
  setups: Setup[];
  onClose: () => void;
  onSaved: () => void;
}

export function AlertForm({ alert, setups, onClose, onSaved }: AlertFormProps) {
  const { t } = useTranslation();
  const [name, setName] = useState(alert?.name ?? '');
  const [source, setSource] = useState<AlertSource>(alert?.source ?? 'price');
  const [setupId, setSetupId] = useState<string>(alert?.setup_id ?? '');
  const [symbol, setSymbol] = useState(alert?.symbol ?? 'BTCUSDT');
  const [interval, setIntervalValue] = useState(alert?.interval ?? '1h');
  const [price, setPrice] = useState<string>(text(alert?.condition?.['price']));
  const [direction, setDirection] = useState<string>(
    text(alert?.condition?.['direction'], 'above'),
  );
  const [expression, setExpression] = useState<string>(text(alert?.condition?.['expression']));
  const [repeat, setRepeat] = useState<RepeatMode>(alert?.repeat_mode ?? 'once_per_bar');
  const [barClose, setBarClose] = useState(alert ? alert.trigger_mode === 'bar_close' : true);
  const [quietFrom, setQuietFrom] = useState<string>(
    alert?.quiet_from_hour === null || alert?.quiet_from_hour === undefined
      ? ''
      : String(alert.quiet_from_hour),
  );
  const [quietTo, setQuietTo] = useState<string>(
    alert?.quiet_to_hour === null || alert?.quiet_to_hour === undefined
      ? ''
      : String(alert.quiet_to_hour),
  );
  const [template, setTemplate] = useState(alert?.template ?? '');
  const [locale, setLocale] = useState<'en' | 'fa'>(alert?.locale ?? 'en');
  const [destinations, setDestinations] = useState<Destination[]>(alert?.destinations ?? []);

  const [preview, setPreview] = useState<alertsApi.Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshPreview = useCallback(async () => {
    try {
      setPreview(await alertsApi.previewTemplate(template, locale));
    } catch {
      setPreview(null);
    }
  }, [template, locale]);

  useEffect(() => {
    const timer = setTimeout(() => void refreshPreview(), 250);
    return () => {
      clearTimeout(timer);
    };
  }, [refreshPreview]);

  const condition = (): Record<string, unknown> => {
    if (source === 'price') return { price: Number(price), direction };
    if (source === 'indicator' || source === 'strategy') return { expression };
    return {};
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const payload: alertsApi.AlertPayload = {
        name: name.trim(),
        source,
        setup_id: setupId || null,
        symbol: symbol.toUpperCase(),
        interval,
        condition: condition(),
        trigger_mode: barClose ? 'bar_close' : 'tick',
        repeat_mode: repeat,
        quiet_from_hour: quietFrom === '' ? null : Number(quietFrom),
        quiet_to_hour: quietTo === '' ? null : Number(quietTo),
        template,
        locale,
        destinations,
      };
      if (alert) await alertsApi.updateAlert(alert.id, payload);
      else await alertsApi.createAlert(payload);
      onSaved();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('alertsPage.form.failed'));
    } finally {
      setBusy(false);
    }
  };

  const addDestination = () => {
    setDestinations((current) => [...current, { kind: 'telegram', target: '' }]);
  };

  return (
    <div
      className={styles.backdrop}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-label={t('alertsPage.form.newTitle')}
      >
        <header className={styles.header}>
          <span className={styles.title}>
            {alert ? t('alertsPage.form.editTitle') : t('alertsPage.form.newTitle')}
          </span>
          <span className={styles.note}>{t('alertsPage.form.note')}</span>
        </header>

        <div className={styles.body}>
          <label className={styles.field}>
            <span className={styles.label}>{t('alertsPage.form.name')}</span>
            <input
              className={styles.input}
              value={name}
              onChange={(event) => {
                setName(event.target.value);
              }}
            />
          </label>

          <div className={styles.row}>
            <label className={styles.field}>
              <span className={styles.label}>{t('alertsPage.form.watches')}</span>
              <select
                className={styles.input}
                value={source}
                onChange={(event) => {
                  setSource(event.target.value as AlertSource);
                }}
              >
                {ALERT_SOURCES.map((key) => (
                  <option key={key} value={key}>
                    {t(`alertsPage.source.${key}`)}
                  </option>
                ))}
              </select>
            </label>

            <label className={styles.field}>
              <span className={styles.label}>{t('alertsPage.form.symbol')}</span>
              <input
                className={styles.input}
                value={symbol}
                onChange={(event) => {
                  setSymbol(event.target.value.toUpperCase());
                }}
              />
            </label>

            <label className={styles.field}>
              <span className={styles.label}>{t('alertsPage.form.timeframe')}</span>
              <select
                className={styles.input}
                value={interval}
                onChange={(event) => {
                  setIntervalValue(event.target.value);
                }}
              >
                {['1m', '15m', '1h', '4h', '1d'].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {source === 'strategy' ? (
            <label className={styles.field}>
              <span className={styles.label}>{t('alertsPage.form.setup')}</span>
              <select
                className={styles.input}
                value={setupId}
                onChange={(event) => {
                  setSetupId(event.target.value);
                }}
              >
                <option value="">{t('alertsPage.form.chooseSetup')}</option>
                {setups.map((setup) => (
                  <option key={setup.id} value={setup.id}>
                    {setup.name} · {setup.strategy_version.slice(0, 8)}
                  </option>
                ))}
              </select>
              <span className={styles.hint}>{t('alertsPage.form.setupHint')}</span>
            </label>
          ) : null}

          {source === 'price' ? (
            <div className={styles.row}>
              <label className={styles.field}>
                <span className={styles.label}>{t('alertsPage.form.crosses')}</span>
                <select
                  className={styles.input}
                  value={direction}
                  onChange={(event) => {
                    setDirection(event.target.value);
                  }}
                >
                  <option value="above">{t('alertsPage.form.above')}</option>
                  <option value="below">{t('alertsPage.form.below')}</option>
                </select>
              </label>
              <label className={styles.field}>
                <span className={styles.label}>{t('alertsPage.form.level')}</span>
                <input
                  className={styles.input}
                  type="number"
                  value={price}
                  onChange={(event) => {
                    setPrice(event.target.value);
                  }}
                />
                <span className={styles.hint}>{t('alertsPage.form.levelHint')}</span>
              </label>
            </div>
          ) : null}

          {source === 'indicator' ? (
            <label className={styles.field}>
              <span className={styles.label}>{t('alertsPage.form.condition')}</span>
              <input
                className={styles.input}
                value={expression}
                placeholder="crossover(close, ema(close, 20))"
                onChange={(event) => {
                  setExpression(event.target.value);
                }}
              />
            </label>
          ) : null}

          <div className={styles.row}>
            <label className={styles.field}>
              <span className={styles.label}>{t('alertsPage.form.repeat')}</span>
              <select
                className={styles.input}
                value={repeat}
                onChange={(event) => {
                  setRepeat(event.target.value as RepeatMode);
                }}
              >
                {REPEAT_MODES.map((key) => (
                  <option key={key} value={key}>
                    {t(`alertsPage.repeat.${key}`)}
                  </option>
                ))}
              </select>
            </label>

            <label className={styles.field}>
              <span className={styles.label}>{t('alertsPage.form.quietFrom')}</span>
              <input
                className={styles.input}
                type="number"
                min={0}
                max={23}
                value={quietFrom}
                onChange={(event) => {
                  setQuietFrom(event.target.value);
                }}
              />
            </label>
            <label className={styles.field}>
              <span className={styles.label}>{t('alertsPage.form.quietUntil')}</span>
              <input
                className={styles.input}
                type="number"
                min={0}
                max={23}
                value={quietTo}
                onChange={(event) => {
                  setQuietTo(event.target.value);
                }}
              />
            </label>
          </div>

          <label className={styles.check}>
            <input
              type="checkbox"
              checked={barClose}
              onChange={(event) => {
                setBarClose(event.target.checked);
              }}
            />
            {t('alertsPage.form.barClose')}
            <span className={styles.hint}>
              A rule checked mid-bar can un-fire: the condition holds, the bar turns, and the signal
              was never real.
            </span>
          </label>

          <div className={styles.field}>
            <span className={styles.label}>{t('alertsPage.form.destinations')}</span>
            {destinations.map((destination, index) => (
              <div key={index} className={styles.row}>
                <select
                  className={styles.input}
                  value={destination.kind}
                  onChange={(event) => {
                    const kind = event.target.value as DestinationKind;
                    setDestinations((current) =>
                      current.map((d, i) => (i === index ? { ...d, kind } : d)),
                    );
                  }}
                >
                  {DESTINATION_KINDS.map((kind) => (
                    <option key={kind} value={kind}>
                      {kind}
                    </option>
                  ))}
                </select>
                <input
                  className={styles.input}
                  value={destination.target}
                  placeholder={t('alertsPage.form.destinationPlaceholder')}
                  onChange={(event) => {
                    const target = event.target.value;
                    setDestinations((current) =>
                      current.map((d, i) => (i === index ? { ...d, target } : d)),
                    );
                  }}
                />
                <button
                  type="button"
                  className={styles.button}
                  onClick={() => {
                    setDestinations((current) => current.filter((_, i) => i !== index));
                  }}
                >
                  <Icon name="trash" size={14} />
                </button>
              </div>
            ))}
            <button type="button" className={styles.button} onClick={addDestination}>
              <Icon name="plus" size={14} />
              {t('alertsPage.form.addDestination')}
            </button>
          </div>

          <label className={styles.field}>
            <span className={styles.label}>{t('alertsPage.form.message')}</span>
            <textarea
              className={styles.textarea}
              rows={4}
              value={template}
              placeholder="{{side_icon}} {{SIDE}} {{symbol}} {{tf}} at {{price}}"
              onChange={(event) => {
                setTemplate(event.target.value);
              }}
            />
            <span className={styles.hint}>{t('alertsPage.form.messageHint')}</span>
          </label>

          <div className={styles.row}>
            <label className={styles.field}>
              <span className={styles.label}>{t('alertsPage.form.language')}</span>
              <select
                className={styles.input}
                value={locale}
                onChange={(event) => {
                  setLocale(event.target.value as 'en' | 'fa');
                }}
              >
                <option value="en">English</option>
                {/* Named in English like everything else on screen: this
                    chooses the language of the message that is sent, not
                    the language of the app. */}
                <option value="fa">Persian</option>
              </select>
            </label>
          </div>

          {preview ? (
            <div className={styles.preview}>
              <span className={styles.label}>{t('alertsPage.form.preview')}</span>
              <pre className={styles.previewBody} dir={locale === 'fa' ? 'rtl' : 'ltr'}>
                {preview.message}
              </pre>
              {preview.unknown_variables.length > 0 ? (
                <p className={styles.warn}>
                  <Icon name="warning" size={12} />
                  {preview.unknown_variables.join(', ')} will not fill in — they stay in the message
                  as written.
                </p>
              ) : null}
              <p className={styles.hint}>{t('alertsPage.form.disclaimerNote')}</p>
            </div>
          ) : null}

          {error ? (
            <p className={styles.error} role="alert">
              {error}
            </p>
          ) : null}
        </div>

        <footer className={styles.footer}>
          <button type="button" className={styles.button} onClick={onClose}>
            {t('alertsPage.form.cancel')}
          </button>
          <button
            type="button"
            className={`${styles.button} ${styles.primary}`}
            disabled={busy || name.trim() === ''}
            onClick={() => {
              void save();
            }}
          >
            {busy
              ? t('alertsPage.form.saving')
              : alert
                ? t('alertsPage.form.saveChanges')
                : t('alertsPage.form.create')}
          </button>
        </footer>
      </div>
    </div>
  );
}
