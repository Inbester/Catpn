/**
 * Line icons: 1.5px stroke, 20px in the rail and 16–18px elsewhere (SPEC §2).
 * The paths follow the shapes used in the approved mockups.
 */

export type IconName =
  | 'chart'
  | 'research'
  | 'test'
  | 'alerts'
  | 'bot'
  | 'resources'
  | 'ai'
  | 'settings'
  | 'account'
  | 'search'
  | 'plus'
  | 'more'
  | 'check'
  | 'close'
  | 'clock'
  | 'history'
  | 'sun'
  | 'moon'
  | 'warning';

const PATHS: Record<IconName, string> = {
  chart: 'M4 19V5M4 19h16M8 15l3-4 3 2 5-6',
  research: 'M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3M7.5 14h9',
  test: 'M4 12h12M12 6l6 6-6 6M20 5v14',
  alerts: 'M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15zM10 20a2 2 0 0 0 4 0',
  bot: 'M5 8h14v11H5zM12 4v4M9 13h.01M15 13h.01M9.5 16.5h5',
  resources: 'M4 20h16M6 11v6M11 7v10M16 4v13',
  ai: 'M12 3l2.2 5.3L20 10l-5.3 2.2L12 18l-2.2-5.8L4 10l5.8-1.7z',
  settings:
    'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6L7 7M17 17l1.4 1.4M5.6 18.4L7 17M17 7l1.4-1.4',
  account: 'M12 12.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM5 20a7 7 0 0 1 14 0',
  search: 'M11 17a6 6 0 1 0 0-12 6 6 0 0 0 0 12zM15.5 15.5L20 20',
  plus: 'M12 5v14M5 12h14',
  more: 'M5 12h.01M12 12h.01M19 12h.01',
  check: 'M4 12.5l5 5L20 6.5',
  close: 'M6 6l12 12M18 6L6 18',
  clock: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2',
  history: 'M3 12a9 9 0 1 0 3-6.7M3 4v4h4M12 7v5l3.5 2',
  sun: 'M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 2v2M12 20v2M4 12H2M22 12h-2M5 5l1.5 1.5M17.5 17.5L19 19M5 19l1.5-1.5M17.5 6.5L19 5',
  moon: 'M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z',
  warning: 'M12 4l9 16H3zM12 10v4M12 17h.01',
};

export interface IconProps {
  name: IconName;
  size?: number;
  /**
   * `| undefined` is explicit because the project enables
   * `exactOptionalPropertyTypes`, and CSS-module lookups are typed as
   * `string | undefined` under `noUncheckedIndexedAccess`.
   */
  className?: string | undefined;
  title?: string | undefined;
}

export function Icon({ name, size = 20, className, title }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      role={title ? 'img' : 'presentation'}
      aria-hidden={title ? undefined : true}
    >
      {title ? <title>{title}</title> : null}
      <path d={PATHS[name]} />
    </svg>
  );
}
