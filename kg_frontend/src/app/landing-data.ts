// Landing-page facts. Every value here was read from the production manual
// databases on 2026-09-16. Nothing is estimated — if the source pages change,
// re-read them rather than editing values by hand.

/** Vehicle configurations with a repair manual on disk (main_db, 2026-09-16). */
export const MANUAL_CONFIGS = 221;
/** Shown publicly as a floor ("۲۲۰+"), so the figure stays true as coverage grows. */
export const MANUAL_CONFIGS_FLOOR = Math.floor(MANUAL_CONFIGS / 10) * 10;

// Hero — repair-manual viewer. Source vehicle: Corolla Cross L, AWD (2024),
// engine M20A-FKS.
//   identify / install — Engine Control System (M20A-FKS) › Ignition Coil And Spark Plug
//                        › Installation [11/2023 - ] (Caution + Procedure)
//   plug torque        — Service Specifications › Maintenance › Torque Specifications
//                        [11/2023 - ] › M20A-FKS Spark Plug
//   labor              — Labor Times › Engine Performance › Ignition Systems › Spark Plugs
//   dtc                — Engine Control System (M20A-FKS) - Diagnostic Codes (2 Of 6)
//                        › SFI SYSTEM › DTC P0300-00 … P0304-00 [11/2023 - ] › Description
export const ENGINE = {
  engine: 'M20A-FKS',
  vehicle: 'Corolla Cross L AWD 2024',
  system: 'Ignition Coil And Spark Plug',
  plugTorque: { nm: '20 N·m', alt: '204 kgf·cm' },
  coilTorque: { nm: '7.5 N·m', alt: '76 kgf·cm' },
  coilSocket: '8 mm',
  laborHours: '0.8',
  dtc: { code: 'P0301-00', title: 'Cylinder 1 Misfire Detected' },
  partCodes: { plug: '19100P', coil: '19500' },
};

// Layer cards — one real job traced through all four layers:
//   manual  — Corolla Cross L, AWD (2024) › Rear Disc Brake Pad › Installation [11/2022 - ] › Procedure
//   labor   — Corolla Cross L, AWD (2024) › Labor Times › Brake Shoes &/Or Pads › Remove & Replace
//   sst     — Corolla Cross L, AWD (2024) › Maintenance (Preparation) › SST [09/2021 - ]
//   parts   — Corolla Cross LE (Parts 2023) › PAD KIT, DISC BRAKE, REAR (11.2022 - 12.2024)
export const SPECIMEN = {
  job: 'تعویض لنت ترمز عقب',
  car: 'Corolla Cross',
  torque: { value: '34.3 N·m', alt: '350 kgf·cm', page: 'Rear Disc Brake Pad · Installation [11/2022 – ]' },
  labor: { hours: '1.2', operation: 'Brake Shoes &/Or Pads · Remove & Replace', appliesTo: 'Rear, Both Sides' },
  sst: { number: '09719-77020', name: 'Disc Brake Piston Spreader Wide Type' },
  part: { number: '04466-02380', name: 'PAD KIT, DISC BRAKE, REAR', nameFa: 'کیت لنت دیسک ترمز عقب', dates: '11.2022 – 12.2024' },
};

const FA_DIGITS = '۰۱۲۳۴۵۶۷۸۹';
/** Latin → Persian digits (and '.' → '٫'). For Persian copy only — never for codes. */
export function fa(v: string | number): string {
  return String(v).replace(/\d/g, (d) => FA_DIGITS[+d]).replace(/(\d|[۰-۹])\.(?=[۰-۹\d])/g, '$1٫');
}
