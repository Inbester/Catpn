/** Number formatting shared across the Test views. */

export function money(value: number, digits = 2): string {
  return value.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function signedMoney(value: number, digits = 2): string {
  return `${value >= 0 ? '+' : ''}${money(value, digits)}`;
}

export function percent(value: number, digits = 2): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`;
}

/** A ratio that may be undefined — never invent a large number for it. */
export function ratio(value: number | null, digits = 2): string {
  return value === null ? '—' : value.toFixed(digits);
}

export function compact(value: number): string {
  return value.toLocaleString('en-US', { notation: 'compact', maximumFractionDigits: 2 });
}

export function price(value: number): string {
  const digits = value >= 1000 ? 1 : value >= 1 ? 2 : 6;
  return money(value, digits);
}

export function timestamp(ms: number, timezone = 'UTC'): string {
  try {
    return new Intl.DateTimeFormat('en-GB', {
      timeZone: timezone,
      year: '2-digit',
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(new Date(ms));
  } catch {
    return new Date(ms).toISOString().slice(0, 16).replace('T', ' ');
  }
}

export function duration(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}
