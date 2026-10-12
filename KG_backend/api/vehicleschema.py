"""schema.org-automotive structured vehicle data (https://schema.org/Car).

Builds one ``VehicleSpec`` per catalog car, shaped like a schema.org ``Car``
object (JSON-LD-ready), from three source tiers — and ONLY from them:

* tier 'catalog'/'stem' — the catalog row (brand, year) and the deterministic
  tokens encoded in the warehouse stem: model, trim, engine displacement,
  engine VIN code, drivetrain, manual transmission, powertrain class.
* tier 'manual'         — spec tables parsed out of the vehicle's own repair
  manual (Quick Lookups → Fluids / Tire Fitment): fluid capacities and types,
  refrigerant, tire sizes, fuel-tank capacity when stated, and an
  automatic-transmission signal (an "Automatic Transmission Fluid" row).
* tier 'curated'        — a small hand-reviewed model→facts table for
  identity facts the manuals genuinely do not contain (bodyType, doors,
  whole-model powertrains like Prius=hybrid, Mirai=hydrogen).

The leave-null policy is strict: a field with no reliable source is simply
ABSENT from ``data`` (never guessed). Every present field has a provenance
record: {field_path: {source, detail}} — auditable per value.

Deliberately NOT populated (no in-fleet source; repair manuals carry service
specs, not marketing specs): enginePower, rated torque, weight, dimensions,
wheelbase, seating capacity, acceleration, emissions, VIN.
"""
import re
import sqlite3

from .rag import config
from . import dataquality

BUILDER_VERSION = 'v1'

# ---------------------------------------------------------------------------
# Curated model facts (hand-reviewed; provenance 'curated'). Keys match the
# model names produced by parse_stem(). Only facts that hold for EVERY variant
# of the model in this fleet's era are listed — anything ambiguous is omitted.
# ---------------------------------------------------------------------------
CURATED_MODEL_FACTS = {
    '4Runner':          {'bodyType': 'SUV', 'numberOfDoors': 5},
    'Camry':            {'bodyType': 'Sedan', 'numberOfDoors': 4},
    'Corolla Cross':    {'bodyType': 'Crossover SUV', 'numberOfDoors': 5},
    'Corolla':          {'bodyType': 'Sedan', 'numberOfDoors': 4},
    'Corolla Hatchback': {'bodyType': 'Hatchback', 'numberOfDoors': 5},
    'GR Corolla':       {'bodyType': 'Hatchback', 'numberOfDoors': 5},
    'GR86':             {'bodyType': 'Coupe', 'numberOfDoors': 2},
    'Grand Highlander': {'bodyType': 'SUV', 'numberOfDoors': 5},
    'Highlander':       {'bodyType': 'SUV', 'numberOfDoors': 5},
    'Crown':            {'bodyType': 'Sedan', 'numberOfDoors': 4,
                         'fuelType': 'Gasoline/Electric Hybrid'},
    'Crown Signia':     {'bodyType': 'SUV', 'numberOfDoors': 5,
                         'fuelType': 'Gasoline/Electric Hybrid'},
    'Land Cruiser':     {'bodyType': 'SUV', 'numberOfDoors': 5},
    'Mirai':            {'bodyType': 'Sedan', 'numberOfDoors': 4,
                         'fuelType': 'Hydrogen (fuel cell)'},
    'Prius':            {'bodyType': 'Hatchback', 'numberOfDoors': 5,
                         'fuelType': 'Gasoline/Electric Hybrid'},
    'Prius Prime':      {'bodyType': 'Hatchback', 'numberOfDoors': 5,
                         'fuelType': 'Gasoline/Electric Plug-in Hybrid'},
    'RAV4':             {'bodyType': 'Crossover SUV', 'numberOfDoors': 5},
    'RAV4 Prime':       {'bodyType': 'Crossover SUV', 'numberOfDoors': 5,
                         'fuelType': 'Gasoline/Electric Plug-in Hybrid'},
    'Sequoia':          {'bodyType': 'SUV', 'numberOfDoors': 5,
                         'fuelType': 'Gasoline/Electric Hybrid'},
    'Sienna':           {'bodyType': 'Minivan', 'numberOfDoors': 5,
                         'fuelType': 'Gasoline/Electric Hybrid'},
    'Supra':            {'bodyType': 'Coupe', 'numberOfDoors': 2},
    'Tacoma':           {'bodyType': 'Pickup Truck'},
    'Tundra':           {'bodyType': 'Pickup Truck'},
    'Venza':            {'bodyType': 'Crossover SUV', 'numberOfDoors': 5,
                         'fuelType': 'Gasoline/Electric Hybrid'},
    'bZ4X':             {'bodyType': 'Crossover SUV', 'numberOfDoors': 5},
    # Lexus (current fleet + likely additions)
    'NX':               {'bodyType': 'Crossover SUV', 'numberOfDoors': 5},
    'RX':               {'bodyType': 'SUV', 'numberOfDoors': 5},
    'UX':               {'bodyType': 'Crossover SUV', 'numberOfDoors': 5},
    'GX':               {'bodyType': 'SUV', 'numberOfDoors': 5},
    'LX':               {'bodyType': 'SUV', 'numberOfDoors': 5},
    'ES':               {'bodyType': 'Sedan', 'numberOfDoors': 4},
    'IS':               {'bodyType': 'Sedan', 'numberOfDoors': 4},
    'LS':               {'bodyType': 'Sedan', 'numberOfDoors': 4},
    'RC':               {'bodyType': 'Coupe', 'numberOfDoors': 2},
    'LC':               {'bodyType': 'Coupe', 'numberOfDoors': 2},
}

# Longest-first so 'Corolla Cross' wins over 'Corolla', 'RAV4 Prime' over
# 'RAV4', 'GR Corolla' over 'Corolla', 'Crown Signia' over 'Crown'.
_MODEL_NAMES = sorted(CURATED_MODEL_FACTS.keys(), key=len, reverse=True)

_YEAR_SUFFIX_RE = re.compile(r'\s*\((\d{4})\)\s*$')
_DISP_RE = re.compile(r'\b(\d\.\d)\s*L\b')
_VIN_RE = re.compile(r'Eng\s+VIN\s+(\w+)', re.IGNORECASE)
_TIRE_RE = re.compile(r'\b\d{3}/\d{2}\s?R\s?\d{2}[A-Z]{0,2}\b')

DRIVE_CONFIGS = {
    'AWD': 'AllWheelDriveConfiguration',
    '4WD': 'FourWheelDriveConfiguration',
    'FWD': 'FrontWheelDriveConfiguration',
    'RWD': 'RearWheelDriveConfiguration',
}

MANUFACTURERS = {'Toyota': 'Toyota Motor Corporation',
                 'Lexus': 'Toyota Motor Corporation'}


def parse_stem(stem):
    """Deterministic decomposition of a warehouse stem into its encoded
    tokens. Handles the multi-year ' (YYYY)' suffix."""
    out = {'stem': stem, 'base': stem, 'year_suffix': None, 'model': None,
           'trim': '', 'displacement_l': None, 'engine_vin': None,
           'drivetrain': None, 'manual_trans': False}
    m = _YEAR_SUFFIX_RE.search(stem)
    base = stem
    if m:
        out['year_suffix'] = int(m.group(1))
        base = stem[:m.start()].strip()
    out['base'] = base

    parts = [p.strip() for p in base.split(',') if p.strip()]
    head, rest = parts[0], parts[1:]
    for tok in rest:
        up = tok.upper()
        if up in DRIVE_CONFIGS:
            out['drivetrain'] = up
            continue
        if 'standard trans' in tok.lower():
            out['manual_trans'] = True
            continue
        dm = _DISP_RE.search(tok)
        if dm:
            out['displacement_l'] = float(dm.group(1))
        vm = _VIN_RE.search(tok)
        if vm:
            out['engine_vin'] = vm.group(1).upper()

    for name in _MODEL_NAMES:
        if head == name or head.startswith(name + ' '):
            out['model'] = name
            out['trim'] = head[len(name):].strip()
            break
    if out['model'] is None:
        # Unknown model line: first comma-group is the closest thing to a
        # model+trim string; leave trim empty rather than guess a split.
        out['model'] = head
    return out


# ---------------------------------------------------------------------------
# Manual spec-table parsing (Quick Lookups)
# ---------------------------------------------------------------------------
_FLUID_KEYWORDS = ('engine oil', 'transmission fluid', 'transaxle', 'coolant',
                   'refrigerant', 'brake fluid', 'differential', 'transfer case',
                   'fuel tank', 'washer fluid', 'power steering')
_MAX_FLUID_ROWS = 40


def _find_leaf(con, patterns):
    for pat in patterns:
        row = con.execute(
            "SELECT path, content FROM nodes WHERE file_type='end_path' "
            "AND content IS NOT NULL AND path LIKE ? "
            "ORDER BY LENGTH(path) LIMIT 1", (pat,)).fetchone()
        if row and row[1]:
            return row
    return None


def _table_rows(html):
    """[(cells...)] for every table row in the section HTML."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    rows = []
    for tr in soup.find_all('tr'):
        cells = [c.get_text(' ', strip=True) for c in tr.find_all(['td', 'th'])]
        cells = [re.sub(r'\s+', ' ', c) for c in cells if c]
        if cells:
            rows.append(cells)
    return rows


def parse_manual_specs(stem):
    """Extract the reliably-parseable spec facts from one car's manual.
    Returns {'fluids': [{name, value}], 'tires': [..], 'auto_trans': bool,
    'fuel_tank_l': float|None, 'sections': [paths]} — empty when the car DB
    or the sections are absent."""
    out = {'fluids': [], 'tires': [], 'auto_trans': False,
           'fuel_tank_l': None, 'sections': []}
    path = config.WAREHOUSE_DIR / f'{stem}.db'
    if not path.exists():
        return out
    try:
        con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    except sqlite3.Error:
        return out
    try:
        # Fluids table: a dedicated "Quick Lookups/Fluids" page where the
        # manual has one; otherwise the fluid rows inside the model's
        # "Common Specs & Procedures" quick-lookup (e.g. 4Runner).
        fl = _find_leaf(con, ['%Quick Lookups/Fluids%',
                              '%Common Specs & Procedures%'])
        if fl:
            out['sections'].append(fl[0])
            for cells in _table_rows(fl[1]):
                label = cells[0]
                low = label.lower()
                if not any(k in low for k in _FLUID_KEYWORDS):
                    continue
                if len(out['fluids']) >= _MAX_FLUID_ROWS:
                    break
                value = ' ; '.join(cells[1:]) if len(cells) > 1 else label
                out['fluids'].append({'name': label, 'value': value})
                if 'automatic transmission fluid' in low:
                    out['auto_trans'] = True
                if 'fuel tank' in low:
                    lm = re.search(r'(\d+(?:\.\d+)?)\s*L\b', value)
                    if lm:
                        out['fuel_tank_l'] = float(lm.group(1))
        tf = _find_leaf(con, ['%Quick Lookups/Tire Fitment%'])
        tire_html = tf[1] if tf else (fl[1] if fl else None)
        if tire_html:
            sizes = sorted(set(_TIRE_RE.findall(
                re.sub(r'<[^>]+>', ' ', tire_html))))[:8]
            if sizes:
                if tf:
                    out['sections'].append(tf[0])
                out['tires'] = sizes
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return out


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def _qv(value, unit_code, unit_text=''):
    q = {'@type': 'QuantitativeValue', 'value': value, 'unitCode': unit_code}
    if unit_text:
        q['unitText'] = unit_text
    return q


def derive(car):
    """(data, provenance, sections) for one catalog Car row."""
    stem = car.car_name
    p = parse_stem(stem)
    curated = CURATED_MODEL_FACTS.get(p['model'], {})
    data = {'@type': 'Car'}
    prov = {}

    def put(field, value, source, detail):
        data[field] = value
        prov[field] = {'source': source, 'detail': detail}

    year = car.year or p['year_suffix']
    display = p['base']
    put('name', f'{year} {car.brand_name} {display}' if year
        else f'{car.brand_name} {display}', 'catalog', 'brand + year + stem')
    put('brand', {'@type': 'Brand', 'name': car.brand_name},
        'catalog', 'main_db.brand_name')
    manufacturer = MANUFACTURERS.get(car.brand_name)
    if manufacturer:
        put('manufacturer', {'@type': 'Organization', 'name': manufacturer},
            'curated', f'brand {car.brand_name}')
    put('model', p['model'], 'stem', f'stem head "{p["base"]}"')
    if year:
        put('vehicleModelDate', str(year), 'catalog', 'main_db.year')
        put('modelDate', str(year), 'catalog', 'main_db.year')
    if p['trim']:
        put('vehicleConfiguration', p['trim'], 'stem', 'trim tokens after model')

    # Powertrain / fuel. Order: curated whole-model fact (Prius, Mirai, ...) >
    # stem markers (bZ4X, 'Hybrid', Lexus 'h') > gasoline default for this
    # Toyota/Lexus fleet (any electrified variant is explicitly marked).
    if 'fuelType' in curated:
        put('fuelType', curated['fuelType'], 'curated', f'model {p["model"]}')
    elif dataquality.is_pure_ev(stem):
        put('fuelType', 'Electric', 'stem', 'pure-EV model marker')
    elif dataquality.is_electrified(stem):
        put('fuelType', 'Gasoline/Electric Hybrid', 'stem', 'hybrid marker in stem')
    else:
        put('fuelType', 'Gasoline', 'derived',
            'no electrified marker in stem (fleet naming marks all hybrids)')

    if p['drivetrain']:
        put('driveWheelConfiguration',
            {'@type': 'DriveWheelConfiguration',
             'name': DRIVE_CONFIGS[p['drivetrain']]},
            'stem', f'token {p["drivetrain"]}')

    if 'bodyType' in curated:
        put('bodyType', curated['bodyType'], 'curated', f'model {p["model"]}')
    if 'numberOfDoors' in curated:
        put('numberOfDoors', curated['numberOfDoors'], 'curated',
            f'model {p["model"]}')

    # Manual-derived facts.
    specs = parse_manual_specs(stem)

    is_ev = data.get('fuelType') == 'Electric'
    engine = {}
    if is_ev:
        engine = {'@type': 'EngineSpecification',
                  'engineType': 'Electric motor', 'fuelType': 'Electric'}
        prov['vehicleEngine'] = {'source': 'stem', 'detail': 'pure-EV model marker'}
    else:
        if p['displacement_l'] is not None:
            engine['engineDisplacement'] = _qv(p['displacement_l'], 'LTR', 'L')
        if p['engine_vin']:
            engine['engineType'] = (
                f'{p["displacement_l"]}L engine, VIN code {p["engine_vin"]}'
                if p['displacement_l'] else f'Engine VIN code {p["engine_vin"]}')
        if engine:
            engine['@type'] = 'EngineSpecification'
            engine['fuelType'] = data.get('fuelType', 'Gasoline')
            prov['vehicleEngine'] = {'source': 'stem',
                                     'detail': 'displacement / VIN-code tokens'}
    if engine:
        data['vehicleEngine'] = engine

    if p['manual_trans']:
        put('vehicleTransmission', 'Manual', 'stem', 'token "Standard Trans"')
    elif specs['auto_trans']:
        put('vehicleTransmission', 'Automatic', 'manual',
            'Automatic Transmission Fluid row in Quick Lookups/Fluids')

    if specs['fuel_tank_l'] is not None:
        put('fuelCapacity', _qv(specs['fuel_tank_l'], 'LTR', 'L'),
            'manual', 'Fuel Tank row in Quick Lookups/Fluids')

    extras = []
    if p['engine_vin']:
        extras.append({'@type': 'PropertyValue', 'name': 'engineVINCode',
                       'value': p['engine_vin']})
    for fluid in specs['fluids']:
        extras.append({'@type': 'PropertyValue',
                       'name': fluid['name'], 'value': fluid['value']})
    if specs['tires']:
        extras.append({'@type': 'PropertyValue', 'name': 'tireSize',
                       'value': ', '.join(specs['tires'])})
    if extras:
        data['additionalProperty'] = extras
        prov['additionalProperty'] = {
            'source': 'manual' if (specs['fluids'] or specs['tires']) else 'stem',
            'detail': '; '.join(specs['sections']) or 'stem tokens'}

    return data, prov, specs['sections']


def build_for_stem(stem, log=None):
    """Build/refresh the VehicleSpec for one cataloged stem."""
    from .models import Car, VehicleSpec
    car = Car.objects.filter(car_name=stem).first()
    if car is None:
        raise ValueError(f'no catalog row for stem {stem!r}')
    data, prov, sections = derive(car)
    VehicleSpec.objects.update_or_create(
        car=car,
        defaults={'data': data, 'provenance': prov, 'sections_used': sections,
                  'builder_version': BUILDER_VERSION})
    if log:
        log(f'vehicle schema built: {stem} ({len(data)} fields)')
    return data


def stale_stems():
    """Catalog stems whose VehicleSpec is missing, built by an older builder,
    or older than the car's warehouse DB file."""
    from .models import Car, VehicleSpec
    specs = {car_id: (ver, built) for car_id, ver, built in
             VehicleSpec.objects.values_list('car_id', 'builder_version', 'built_at')}
    out = []
    for car_id, stem in Car.objects.values_list('id', 'car_name'):
        sp = specs.get(car_id)
        if sp is None or sp[0] != BUILDER_VERSION:
            out.append(stem)
            continue
        p = config.WAREHOUSE_DIR / f'{stem}.db'
        try:
            if p.exists() and p.stat().st_mtime > sp[1].timestamp():
                out.append(stem)
        except OSError:
            pass
    return sorted(out)


def jsonld(data):
    """Full JSON-LD object (adds @context)."""
    return {'@context': 'https://schema.org', **data}


# Identity subset that is safe for public page markup (no service-spec detail
# from the licensed manual content).
_PUBLIC_KEYS = ('@type', 'name', 'brand', 'manufacturer', 'model',
                'vehicleModelDate', 'modelDate', 'vehicleConfiguration',
                'bodyType', 'numberOfDoors', 'fuelType',
                'driveWheelConfiguration', 'vehicleTransmission')


def public_jsonld(data):
    return {'@context': 'https://schema.org',
            **{k: data[k] for k in _PUBLIC_KEYS if k in data}}


def compact_block(data, max_lines=15):
    """Small 'SPECS' text block for chatbot grounding — key: value lines,
    faithful to the stored fields only."""
    lines = []

    def add(label, val):
        if val is not None and len(lines) < max_lines:
            lines.append(f'{label}: {val}')

    add('Vehicle', data.get('name'))
    add('Body type', data.get('bodyType'))
    add('Fuel type', data.get('fuelType'))
    dw = data.get('driveWheelConfiguration')
    add('Drive', dw.get('name') if isinstance(dw, dict) else dw)
    add('Transmission', data.get('vehicleTransmission'))
    eng = data.get('vehicleEngine') or {}
    if isinstance(eng, dict):
        disp = eng.get('engineDisplacement')
        if isinstance(disp, dict):
            add('Engine displacement', f'{disp.get("value")} {disp.get("unitText", "L")}')
        add('Engine', eng.get('engineType'))
    fc = data.get('fuelCapacity')
    if isinstance(fc, dict):
        add('Fuel tank', f'{fc.get("value")} {fc.get("unitText", "L")}')
    for pv in (data.get('additionalProperty') or []):
        if len(lines) >= max_lines:
            break
        add(pv.get('name'), pv.get('value'))
    return '\n'.join(lines)
