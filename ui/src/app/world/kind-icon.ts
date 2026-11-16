/**
 * A kind's `icon` is a Material Symbols name. The app loads nothing from other hosts, so the sidebar draws
 * icons from this small local set (inline SVG paths on a 24-unit grid) and falls back to the kind's first letter.
 */
const PATHS: Record<string, string> = {
  landscape: 'M14 6l-3.75 5 2.85 3.8-1.6 1.2C9.81 13.75 7 10 7 10l-6 8h22L14 6z',
  person: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z',
  category: 'M12 2l-5.5 9h11L12 2zm5.5 11a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9zM3 13.5h8v8H3v-8z',
  key: 'M7 14a3 3 0 1 1 2.83-4H21v3h-2v2h-3v-2h-6.17A3 3 0 0 1 7 14z',
  chat: 'M20 2H4a2 2 0 0 0-2 2v18l4-4h14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2z',
  place: 'M12 2a7 7 0 0 0-7 7c0 5.25 7 13 7 13s7-7.75 7-13a7 7 0 0 0-7-7zm0 9.5a2.5 2.5 0 1 1 0-5 2.5 2.5 0 0 1 0 5z',
};

export function kindIconPath(icon: string | null | undefined): string | null {
  return (icon && PATHS[icon]) || null;
}

export function kindInitial(label: string): string {
  return (label.trim().charAt(0) || '?').toUpperCase();
}
