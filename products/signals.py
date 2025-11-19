from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Product
from .tasks import enqueue_webhook_event

@receiver(post_save, sender=Product)
def product_saved(sender, instance, created, **kwargs):
    event = 'product.created' if created else 'product.updated'
    payload = {
        'id': str(instance.id),
        'sku': instance.sku,
        'name': instance.name,
        'price': float(instance.price) if instance.price is not None else None,
    }
    enqueue_webhook_event.delay(event, payload)

@receiver(post_delete, sender=Product)
def product_deleted(sender, instance, **kwargs):
    event = 'product.deleted'
    payload = {'id': str(instance.id), 'sku': instance.sku}
    enqueue_webhook_event.delay(event, payload)
