from django.contrib import admin
from .models import Product, Webhook

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('sku','name','price','active','created_at')
    search_fields = ('sku','name')

@admin.register(Webhook)
class WebhookAdmin(admin.ModelAdmin):
    list_display = ('url','event','enabled','created_at')
    list_filter = ('event','enabled')
