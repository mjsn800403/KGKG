// Persian/Arabic digits -> ASCII and drop everything but digits (and a
// leading +), so no one can save a phone the SMS operator rejects.
export function normalizePhone(v) {
  const s = String(v ?? '')
    .replace(/[۰-۹]/g, (d) => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d)))
    .replace(/[٠-٩]/g, (d) => String('٠١٢٣٤٥٦٧٨٩'.indexOf(d)))
    .trim();
  const digits = s.replace(/\D/g, '');
  return s.startsWith('+') ? '+' + digits : digits;
}
