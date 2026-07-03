from django.contrib import admin

from .models import PurchaseRequest


@admin.register(PurchaseRequest)
class PurchaseRequestAdmin(admin.ModelAdmin):
    list_display = ('company', 'brand', 'model', 'year', 'mobile', 'handled', 'created_at')
    list_filter = ('handled', 'brand', 'created_at')
    search_fields = ('company', 'brand', 'model', 'reg_no', 'mobile', 'landline')
    list_editable = ('handled',)
    readonly_fields = ('created_at',)
