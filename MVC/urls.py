from django.conf import settings
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import include, path, re_path
from django.views.static import serve


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
    path('billing/', include('billing.urls')),
    path('ml/', include('ml.urls')),
    # Uploaded files (profile pictures, logos, report images/PDFs) are only for logged-in users.
    # Served by Django so the app also works without a separate web server; put nginx in front for heavy use.
    re_path(r'^media/(?P<path>.*)$', login_required(serve), {'document_root': settings.MEDIA_ROOT}),
]
