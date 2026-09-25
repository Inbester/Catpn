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
  | 'warning'
  | 'eye'
  | 'eyeOff'
  | 'cursor'
  | 'trendLine'
  | 'horizontalLine'
  | 'verticalLine'
  | 'ray'
  | 'channel'
  | 'fib'
  | 'rectangle'
  | 'brush'
  | 'text'
  | 'ruler'
  | 'magnet'
  | 'lock'
  | 'unlock'
  | 'trash'
  | 'layers'
  | 'chevronDown'
  | 'camera'
  | 'fullscreen'
  | 'undo'
  | 'redo';

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
  eye: 'M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6-10-6-10-6zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',
  eyeOff:
    'M4 4l16 16M10 6.2A9.8 9.8 0 0 1 12 6c6.4 0 10 6 10 6a17 17 0 0 1-3.2 3.8M6.5 8.3A17 17 0 0 0 2 12s3.6 6 10 6a9.9 9.9 0 0 0 3.3-.55M9.9 9.9a3 3 0 0 0 4.2 4.2',
  cursor: 'M5 3l6 18 2.5-7.5L21 11z',
  trendLine: 'M4 20L20 4M4 20h.01M20 4h.01',
  horizontalLine: 'M3 12h18M6 12h.01M18 12h.01',
  verticalLine: 'M12 3v18M12 6v.01M12 18v.01',
  ray: 'M4 20L16 8M20 4l-4 4M4 20h.01',
  channel: 'M3 17L13 7M7 21L17 11',
  fib: 'M3 5h18M3 10h18M3 14h18M3 19h18',
  rectangle: 'M4 6h16v12H4z',
  brush: 'M4 20c2-1 2-4 4-5s3 1 5-1 2-5 4-6',
  text: 'M5 5h14M12 5v14M9 19h6',
  ruler: 'M3 14l11-11 7 7-11 11zM8 9l2 2M11 6l2 2M5 12l2 2',
  magnet: 'M7 4v7a5 5 0 0 0 10 0V4M7 4H4v7a8 8 0 0 0 16 0V4h-3',
  lock: 'M6 11h12v9H6zM9 11V7.5a3 3 0 0 1 6 0V11',
  unlock: 'M6 11h12v9H6zM9 11V7.5a3 3 0 0 1 5.6-1.5',
  trash: 'M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13M10 11v6M14 11v6',
  layers: 'M12 3l9 5-9 5-9-5zM3 13l9 5 9-5M3 17l9 5 9-5',
  chevronDown: 'M6 9l6 6 6-6',
  camera: 'M4 8h3l2-2h6l2 2h3v12H4zM12 17a4 4 0 1 0 0-8 4 4 0 0 0 0 8z',
  fullscreen: 'M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5',
  undo: 'M9 14L4 9l5-5M4 9h10a6 6 0 0 1 0 12h-3',
  redo: 'M15 14l5-5-5-5M20 9H10a6 6 0 0 0 0 12h3',
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
