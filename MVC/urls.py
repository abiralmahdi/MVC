from django.contrib import admin
from django.urls import path
from django.urls import include
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('home.urls')),
    path('accounts/', include('accounts.urls')),
    path('settings/', include('dynamic.urls')),
    path('dashboard/', include('dashboard.urls')),
    path('alarms/', include('alarms.urls')),
    path('reports/', include('report.urls')),
    path('location/', include('location.urls')),
    path('api/', include('api.urls')),
    path('scada/', include('scada.urls')),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)