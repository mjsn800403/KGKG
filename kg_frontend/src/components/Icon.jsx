// Central inline-SVG icon set — one consistent stroke style everywhere,
// themable via currentColor, zero network/icon-font dependency.
// Usage: <Icon name="car" /> — size via CSS (svg{width/height}) or `size` prop.

const PATHS = {
  // theme
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </>
  ),
  moon: <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />,
  // vehicle / fleet
  car: (
    <>
      <path d="M4 16v2a1 1 0 0 0 1 1h1a1 1 0 0 0 1-1v-1h10v1a1 1 0 0 0 1 1h1a1 1 0 0 0 1-1v-2l-2.2-6.2A2 2 0 0 0 15.9 8H8.1a2 2 0 0 0-1.9 1.4L4 16Z" />
      <path d="M4 16h16M7.5 12.5h.01M16.5 12.5h.01" />
    </>
  ),
  // doc layers
  parts: (
    <>
      <path d="M21 8.5 12 4 3 8.5l9 4.5 9-4.5Z" />
      <path d="M3 8.5V15l9 4.5 9-4.5V8.5" />
      <path d="M12 13v6.5" />
    </>
  ),
  manual: (
    <>
      <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5v-15Z" />
      <path d="M4 20.5A2.5 2.5 0 0 1 6.5 18H20M8 7.5h8M8 11h5" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3.5 2" />
    </>
  ),
  wrench: (
    <path d="M14.7 6.3a4.5 4.5 0 0 0-6 5.6L3 17.6a2 2 0 1 0 2.8 2.8l5.7-5.7a4.5 4.5 0 0 0 5.6-6L14 11.8l-2.4-.6-.6-2.4 3.7-2.5Z" />
  ),
  wiring: (
    <>
      <circle cx="5" cy="6" r="2" />
      <circle cx="19" cy="18" r="2" />
      <path d="M7 6h7a3 3 0 0 1 3 3v0a3 3 0 0 1-3 3H10a3 3 0 0 0-3 3v0a3 3 0 0 0 3 3h7" />
    </>
  ),
  catalog: (
    <>
      <path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4z" />
      <path d="M16.5 13v7M13 16.5h7" />
    </>
  ),
  bulletin: (
    <>
      <path d="M5 4h14v13H12l-4 3.5V17H5V4Z" />
      <path d="M8.5 8.5h7M8.5 12h4.5" />
    </>
  ),
  // chat / assistant
  bot: (
    <>
      <rect x="5" y="8" width="14" height="10" rx="3" />
      <path d="M12 8V5M12 5a1.5 1.5 0 1 0-.01-3A1.5 1.5 0 0 0 12 5ZM2.5 13.5h2M19.5 13.5h2" />
      <path d="M9 12.5h.01M15 12.5h.01M9.5 15.5c.8.7 4.2.7 5 0" />
    </>
  ),
  send: <path d="M21 3 10.5 13.5M21 3l-6.8 18-3.7-7.5L3 9.8 21 3Z" />,
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.8-3.8" />
    </>
  ),
  // contact / footer
  phone: <path d="M5 3h4l1.7 4.6-2.2 1.6a12 12 0 0 0 6.3 6.3l1.6-2.2L21 15v4a2 2 0 0 1-2.2 2A17 17 0 0 1 3 5.2 2 2 0 0 1 5 3Z" />,
  mail: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="m3.5 7 8.5 6 8.5-6" />
    </>
  ),
  building: (
    <>
      <path d="M4 21V5a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v16M15 9h4a1 1 0 0 1 1 1v11M2.5 21h19" />
      <path d="M7.5 7.5h2M7.5 11h2M7.5 14.5h2M11.5 7.5h.01M11.5 11h.01M11.5 14.5h.01" />
    </>
  ),
  // nav / misc
  gear: (
    <>
      <circle cx="12" cy="12" r="3.2" />
      <path d="M19 12a7 7 0 0 0-.14-1.4l2-1.55-2-3.46-2.35.95a7 7 0 0 0-2.42-1.4L13.7 2.6h-3.4l-.4 2.54a7 7 0 0 0-2.42 1.4l-2.34-.95-2 3.46 2 1.55a7.1 7.1 0 0 0 0 2.8l-2 1.55 2 3.46 2.34-.95a7 7 0 0 0 2.43 1.4l.39 2.54h3.4l.4-2.54a7 7 0 0 0 2.41-1.4l2.35.95 2-3.46-2-1.55A7 7 0 0 0 19 12Z" />
    </>
  ),
  cart: (
    <>
      <circle cx="9" cy="20" r="1.5" />
      <circle cx="17" cy="20" r="1.5" />
      <path d="M3 3.5h2.5l2.3 11.5a1.5 1.5 0 0 0 1.5 1.2h7.6a1.5 1.5 0 0 0 1.4-1.1L20.5 8H6" />
    </>
  ),
  logout: (
    <>
      <path d="M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4" />
      <path d="M10 8 6 12l4 4M6 12h10" />
    </>
  ),
  user: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4.5 20.5a7.5 7.5 0 0 1 15 0" />
    </>
  ),
  shield: (
    <>
      <path d="M12 2.5 4.5 5.5v6c0 4.6 3.2 8 7.5 10 4.3-2 7.5-5.4 7.5-10v-6L12 2.5Z" />
      <path d="m9 11.5 2.2 2.2L15.5 9.5" />
    </>
  ),
  bell: (
    <>
      <path d="M18 9a6 6 0 1 0-12 0c0 6-2.5 7-2.5 7h17S18 15 18 9Z" />
      <path d="M10.2 20a2 2 0 0 0 3.6 0" />
    </>
  ),
  check: <path d="m4.5 12.5 5 5L19.5 7" />,
  x: <path d="M6 6l12 12M18 6 6 18" />,
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5M12 8h.01" />
    </>
  ),
  question: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.5 9.2a2.6 2.6 0 0 1 5.1.8c0 1.7-2.6 2.2-2.6 3.7M12 17h.01" />
    </>
  ),
  arrow: <path d="M19 12H5M11 6l-6 6 6 6" />,
  // team / management
  users: (
    <>
      <circle cx="9" cy="8" r="3.5" />
      <path d="M2.5 20a6.5 6.5 0 0 1 13 0" />
      <path d="M16 5.2a3.5 3.5 0 0 1 0 6.6M17.5 14.2A6.5 6.5 0 0 1 21.5 20" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  trash: (
    <>
      <path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13" />
      <path d="M10 11v6M14 11v6" />
    </>
  ),
  edit: (
    <>
      <path d="M4 20h4L18.5 9.5a2 2 0 0 0-2.8-2.8L5 17.2 4 20Z" />
      <path d="M14 6.5l3.5 3.5" />
    </>
  ),
  link: (
    <>
      <path d="M9 15l6-6" />
      <path d="M11 6.5 12.8 4.7a3.5 3.5 0 0 1 5 5L16 11.5M13 17.5 11.2 19.3a3.5 3.5 0 0 1-5-5L8 12.5" />
    </>
  ),
  copy: (
    <>
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1" />
    </>
  ),
  refresh: (
    <>
      <path d="M20 11a8 8 0 0 0-14-4.5L4 8M4 4v4h4" />
      <path d="M4 13a8 8 0 0 0 14 4.5L20 16M20 20v-4h-4" />
    </>
  ),
  chart: (
    <>
      <path d="M4 20V4M4 20h16" />
      <path d="M8 20v-6M12 20V8M16 20v-9M20 20V6" />
    </>
  ),
  org: (
    <>
      <rect x="9" y="3" width="6" height="4" rx="1" />
      <rect x="3" y="16" width="6" height="4" rx="1" />
      <rect x="15" y="16" width="6" height="4" rx="1" />
      <path d="M12 7v4M6 16v-2.5a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1V16" />
    </>
  ),
  sparkles: (
    <>
      <path d="M12 3l1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6L12 3Z" />
      <path d="M18.5 14.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7.7-1.8Z" />
    </>
  ),
  mailplus: (
    <>
      <path d="M3 6.5A1.5 1.5 0 0 1 4.5 5H15a1.5 1.5 0 0 1 1.5 1.5v5" />
      <path d="m3.5 7 6.5 4.5L14 8.7" />
      <path d="M18 15v6M15 18h6" />
    </>
  ),
  chevron: <path d="m6 9 6 6 6-6" />,
  grip: (
    <>
      <circle cx="9" cy="6" r="1.2" /><circle cx="15" cy="6" r="1.2" />
      <circle cx="9" cy="12" r="1.2" /><circle cx="15" cy="12" r="1.2" />
      <circle cx="9" cy="18" r="1.2" /><circle cx="15" cy="18" r="1.2" />
    </>
  ),
  download: (
    <>
      <path d="M12 3v12" />
      <path d="m7 11 5 5 5-5" />
      <path d="M4 20h16" />
    </>
  ),
  pdf: (
    <>
      <path d="M6 2h8l5 5v13a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2Z" />
      <path d="M14 2v5h5" />
      <path d="M8.5 16.5v-4h1.4a1.3 1.3 0 0 1 0 2.6H8.5M13 16.5v-4h1a1.6 2 0 0 1 0 4h-1Z" />
    </>
  ),
  layers: (
    <>
      <path d="m12 3 9 5-9 5-9-5 9-5Z" />
      <path d="m3 12.5 9 5 9-5" />
      <path d="m3 17 9 5 9-5" />
    </>
  ),
  home: (
    <>
      <path d="m4 11 8-7 8 7" />
      <path d="M6 9.5V20h4.5v-5h3v5H18V9.5" />
    </>
  ),
  back: <path d="m14 6-6 6 6 6" />,
};

export default function Icon({ name, size = undefined, style = undefined, className = undefined }) {
  const path = PATHS[name] || PATHS.info;
  const s = size ? { width: size, height: size, ...style } : style;
  // width/height attributes give a sane default (CSS `svg{width:…}` rules still
  // win where set), so an unstyled <Icon/> never renders at the 300x150 default.
  const dim = size || 18;
  return (
    <svg
      viewBox="0 0 24 24"
      width={dim}
      height={dim}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
      style={s}
    >
      {path}
    </svg>
  );
}
