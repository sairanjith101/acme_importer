from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ProductViewSet, upload_csv, upload_progress, WebhookViewSet, ui_view  # note ui_view imported

router = DefaultRouter()
router.register('products', ProductViewSet, basename='product')
router.register('webhooks', WebhookViewSet, basename='webhook')

urlpatterns = [
    path('api/', include(router.urls)),
    path('api/upload/', upload_csv),
    path('api/upload/<str:upload_id>/progress/', upload_progress),
    path('', ui_view, name='index'),  # use ui_view here
]
