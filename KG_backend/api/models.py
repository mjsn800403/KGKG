from django.db import models

class Car(models.Model):
    brand_name = models.TextField()
    car_name = models.TextField()
    year = models.IntegerField()
    db_address = models.TextField()
    
    class Meta:
        db_table = 'main_db'  # Your actual table name


class PurchaseRequest(models.Model):
    """A legal-entity request to purchase technical documentation for a vehicle.

    The sales team follows up on these; the public form (frontend /purchase)
    writes here and the buyer sees a "we'll contact you" confirmation.
    """
    # Vehicle
    brand = models.CharField(max_length=120)
    model = models.CharField(max_length=200)
    year = models.CharField(max_length=20)
    # Requested documents (list of ids: parts / manual / standard_time /
    # special_tools / full_spec) stored as JSON so it stays flexible.
    documents = models.JSONField(default=list, blank=True)
    # Legal-entity contact
    company = models.CharField(max_length=200)
    landline = models.CharField(max_length=40)
    mobile = models.CharField(max_length=40)
    reg_no = models.CharField('registration number', max_length=60)
    note = models.TextField(blank=True, default='')
    # Bookkeeping
    handled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.company} — {self.brand} {self.model} {self.year}'