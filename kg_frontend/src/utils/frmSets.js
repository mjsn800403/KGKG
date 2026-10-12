// Flat-rate manual sets ("زمان استاندارد تعمیراتی") shown as a label on a model
// family in the brand/year browse list. Data + access gate live in the backend
// (api/frm.py); keep the keys here in step with its FRM_SETS.
export const FRM_TITLE = 'زمان استاندارد تعمیراتی';

export const FRM_SETS = [
  { slug: 'toyota-corolla-cross', brand: 'Toyota', family: 'Corolla Cross', years: [2025] },
];

export function frmSetFor(brand, family, year) {
  return FRM_SETS.find((s) =>
    s.brand.toLowerCase() === String(brand).toLowerCase()
    && s.family.toLowerCase() === String(family).toLowerCase()
    && s.years.includes(Number(year))) || null;
}

export function frmSetBySlug(slug) {
  return FRM_SETS.find((s) => s.slug === slug) || null;
}

// Synthetic vehicle rows for the car lists: one card per set and year, shown
// next to the real trims, only when the list already holds a car of that
// family+year (i.e. the user can open it).
export function frmVehicleRows(realRows, keyOf) {
  const out = [];
  FRM_SETS.forEach((s) => s.years.forEach((y) => {
    const has = realRows.some((r) => {
      const v = keyOf(r);
      return String(v.brand).toLowerCase() === s.brand.toLowerCase()
        && Number(v.year) === y
        && String(v.model).toLowerCase().startsWith(s.family.toLowerCase());
    });
    if (has) out.push({ brand_name: s.brand, car_name: s.family, year: y, frm: s.slug });
  }));
  return out;
}
