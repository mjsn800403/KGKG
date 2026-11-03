// Which content a fleet vehicle actually holds, from the backend's additive
// has_manual / has_parts flags (api/portal.py fleet_view). has_manual is true
// when the manual DB exists on disk or is loaded in PostgreSQL; has_parts is
// true only for a parts SQLite file on disk the seat is granted. Nothing here
// assumes a catalog exists.

/** True only when the parts catalog is the vehicle's sole content. Strict on
 *  purpose: a payload without has_manual (older backend) is never labelled. */
export function isPartsOnly(car) {
  return !!car && car.has_parts === true && car.has_manual === false;
}
