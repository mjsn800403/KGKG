// Which content a fleet vehicle actually holds, from the backend's additive
// has_manual / has_parts flags (api/portal.py fleet_view). Both flags come from
// on-disk database checks, so nothing here assumes a catalog exists.

/** True only when the parts catalog is the vehicle's sole content. Strict on
 *  purpose: a payload without has_manual (older backend) is never labelled. */
export function isPartsOnly(car) {
  return !!car && car.has_parts === true && car.has_manual === false;
}
