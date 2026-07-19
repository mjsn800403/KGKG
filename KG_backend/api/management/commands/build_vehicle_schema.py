"""Build the schema.org-shaped VehicleSpec rows.

    manage.py build_vehicle_schema             # only missing/stale cars
    manage.py build_vehicle_schema --force     # rebuild every cataloged car
    manage.py build_vehicle_schema --stems "bZ4X Nightshade" "Camry LE, 2.5L Eng VIN A"
"""
from django.core.management.base import BaseCommand

from api import vehicleschema
from api.models import Car


class Command(BaseCommand):
    help = 'Derive schema.org vehicle specs (VehicleSpec) from catalog/stem/manual data.'

    def add_arguments(self, parser):
        parser.add_argument('--stems', nargs='*', default=None,
                            help='Specific stems to (re)build.')
        parser.add_argument('--force', action='store_true',
                            help='Rebuild all cataloged cars, stale or not.')

    def handle(self, *args, **opts):
        if opts['stems']:
            todo = opts['stems']
        elif opts['force']:
            todo = sorted(Car.objects.values_list('car_name', flat=True))
        else:
            todo = vehicleschema.stale_stems()
        if not todo:
            self.stdout.write('nothing to do — all vehicle specs are current.')
            return
        ok = failed = 0
        for stem in todo:
            try:
                data = vehicleschema.build_for_stem(stem, log=self.stdout.write)
                ok += 1
            except Exception as e:
                failed += 1
                self.stderr.write(f'!! {stem}: {e.__class__.__name__}: {e}')
        self.stdout.write(self.style.SUCCESS(
            f'vehicle schema: {ok} built, {failed} failed '
            f'(builder {vehicleschema.BUILDER_VERSION})'))
