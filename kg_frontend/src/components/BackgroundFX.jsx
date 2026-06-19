'use client';

import { useEffect } from 'react';

export default function BackgroundFX() {
  useEffect(() => {
    function onMove(e) {
      const x = (e.clientX / window.innerWidth * 100).toFixed(2);
      const y = (e.clientY / window.innerHeight * 100).toFixed(2);
      document.documentElement.style.setProperty('--mx', x + '%');
      document.documentElement.style.setProperty('--my', y + '%');
    }
    document.addEventListener('mousemove', onMove);
    return () => document.removeEventListener('mousemove', onMove);
  }, []);

  return (
    <>
      <div className="blueprint" />
      <div className="orb orb1" />
      <div className="orb orb2" />
      <div className="scanline" />
      <div id="spotlight" />
    </>
  );
}
