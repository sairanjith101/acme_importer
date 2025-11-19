from rest_framework import serializers
from .models import Product, Webhook

class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        # include fields explicitly for clarity
        fields = [
            'id',
            'sku',
            'name',
            'description',
            'price',
            'active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ('id', 'created_at', 'updated_at')

class WebhookSerializer(serializers.ModelSerializer):
    class Meta:
        model = Webhook
        fields = [
            'id',
            'url',
            'event',
            'enabled',
            'created_at',
        ]
        read_only_fields = ('id', 'created_at')
