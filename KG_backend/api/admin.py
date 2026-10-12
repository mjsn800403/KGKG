from django.contrib import admin

from .models import (
    ActivityLog, Company, CompanyCarAccess, PortalUser, PurchaseRequest,
    UserCarAccess,
)


@admin.register(PurchaseRequest)
class PurchaseRequestAdmin(admin.ModelAdmin):
    list_display = ('company', 'brand', 'model', 'year', 'mobile',
                    'employees_count', 'seats_count', 'wants_demo', 'status', 'created_at')
    list_filter = ('status', 'wants_demo', 'brand', 'created_at')
    search_fields = ('company', 'brand', 'model', 'reg_no', 'mobile', 'landline')
    readonly_fields = ('created_at',)


class CompanyCarAccessInline(admin.TabularInline):
    model = CompanyCarAccess
    extra = 0


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'seats_count', 'is_demo', 'ai_assistant_enabled', 'active', 'created_at')
    list_filter = ('is_demo', 'active')
    search_fields = ('name', 'reg_no')
    inlines = [CompanyCarAccessInline]


class UserCarAccessInline(admin.TabularInline):
    model = UserCarAccess
    extra = 0


@admin.register(PortalUser)
class PortalUserAdmin(admin.ModelAdmin):
    list_display = ('username', 'company', 'role', 'active', 'last_login_at')
    list_filter = ('role', 'active', 'company')
    search_fields = ('username', 'display_name')
    inlines = [UserCarAccessInline]


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'action', 'detail', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('user__username', 'detail')
