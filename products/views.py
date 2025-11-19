from django.shortcuts import render
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from .models import Product, Webhook
from .serializers import ProductSerializer, WebhookSerializer
from django.shortcuts import render
from .tasks import import_products_task, enqueue_webhook_event, bulk_delete_task
import redis, uuid, os, json, tempfile
from django.conf import settings

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
r = redis.from_url(REDIS_URL)

def ui_view(request):
    return render(request, 'ui.html')

class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all().order_by('-updated_at')
    serializer_class = ProductSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['sku','name','description']
    ordering_fields = ['sku','name','price','created_at','updated_at']

    @action(detail=False, methods=['post'])
    def bulk_delete(self, request):
        confirm = request.data.get('confirm', False)
        if not confirm:
            return Response({'detail':'confirmation required'}, status=status.HTTP_400_BAD_REQUEST)
        task_id = str(uuid.uuid4())
        bulk_delete_task.delay(task_id)
        return Response({'task_id': task_id})

@api_view(['POST'])
def upload_csv(request):
    """
    Accepts CSV file via form-data 'file' field.
    Saves file to temporary location and starts Celery task.
    """
    upload_id = str(uuid.uuid4())
    file = request.FILES.get('file')
    if not file:
        return Response({'detail':'file required'}, status=status.HTTP_400_BAD_REQUEST)
    # save to temp file
    tmpdir = getattr(settings, 'MEDIA_ROOT', '/tmp')
    os.makedirs(tmpdir, exist_ok=True)
    tmp_path = os.path.join(tmpdir, f'upload_{upload_id}.csv')
    with open(tmp_path, 'wb') as out:
        for chunk in file.chunks():
            out.write(chunk)
    r.set(f'upload:{upload_id}:progress', json.dumps({'status':'queued','percent':0}))
    import_products_task.delay(upload_id, tmp_path)
    return Response({'upload_id': upload_id})

@api_view(['GET'])
def upload_progress(request, upload_id):
    data = r.get(f'upload:{upload_id}:progress')
    if not data:
        return Response({'status':'not_found'}, status=404)
    return Response(json.loads(data))

class WebhookViewSet(viewsets.ModelViewSet):
    queryset = Webhook.objects.all().order_by('-created_at')
    serializer_class = WebhookSerializer

    @action(detail=True, methods=['POST'])
    def test(self, request, pk=None):
        wh = self.get_object()
        payload = request.data.get('payload', {'test': True})
        # Fire webhook in background
        enqueue_webhook_event.delay(wh.event, payload)
        return Response({'status':'triggered'})

    @action(detail=True, methods=['GET'])
    def logs(self, request, pk=None):
        wh = self.get_object()
        logs = r.lrange(f'webhook:log:{wh.id}', 0, 49)
        decoded = [json.loads(x) for x in logs]
        return Response({'logs': decoded})
