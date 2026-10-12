"""Keep «all cars» companies whole: a car added to the platform later is
granted to every company whose plan promises all cars (Company.all_cars)."""
import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Car, Company

log = logging.getLogger(__name__)


@receiver(post_save, sender=Car)
def grant_new_car_to_all_cars_companies(sender, instance, created, **kwargs):
    if not created:
        return

    def _grant():
        from .portal import grant_all_cars
        for company in Company.objects.filter(all_cars=True):
            try:
                grant_all_cars(company)
            except Exception:
                log.exception('auto-grant of car %s to company %s failed', instance.id, company.id)

    transaction.on_commit(_grant)
