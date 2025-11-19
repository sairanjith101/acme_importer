"""
URL configuration for acme_importer project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
import redis, os, json
REDIS_URL = os.getenv('REDIS_URL','redis://localhost:6379/0')
r = redis.from_url(REDIS_URL)

def redis_probe(request):
    key = request.GET.get('key')
    if not key:
        return JsonResponse({'error':'missing key'}, status=400)
    val = r.get(key)
    if not val:
        return JsonResponse({}, status=200, safe=False)
    return JsonResponse(json.loads(val), safe=False)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('products.urls')),
    path('__redis_probe', redis_probe),  # dev-only
]

