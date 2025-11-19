from django.db import models
import uuid

class Product(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sku = models.CharField(max_length=200, unique=True)
    name = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['sku']),
            models.Index(fields=['name']),
        ]

    def save(self, *args, **kwargs):
        if self.sku:
            self.sku = self.sku.strip()
        super().save(*args, **kwargs)

class Webhook(models.Model):
    EVENT_CHOICES = [
        ('product.created','Product Created'),
        ('product.updated','Product Updated'),
        ('product.deleted','Product Deleted'),
        ('import.completed','Import Completed'),
    ]
    url = models.URLField()
    event = models.CharField(max_length=100, choices=EVENT_CHOICES)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
