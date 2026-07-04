'use client';

import { useEffect, useState } from 'react';
import { getPortalUser } from '../utils/api';

// Topbar identity chip. Shows the logged-in seat's company + role; falls back
// to the platform brand when no portal session exists.
export default function UserChip() {
  const [user, setUser] = useState(null);
  useEffect(() => { setUser(getPortalUser()); }, []);

  const label = user
    ? `${user.company} — ${user.role_label || ''}`
    : 'KGTECHVAULT Company';
  const avatar = user?.username ? user.username.slice(0, 2).toUpperCase() : 'KG';

  return (
    <div className="userchip">
      <div className="avatar">{avatar}</div> {label}
    </div>
  );
}
