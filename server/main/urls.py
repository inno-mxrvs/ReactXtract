from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path

from . import views


urlpatterns = [
    path('', views.home, name='home'),
    path('extract/', views.extract_documents, name='extract_documents'),
    path('records/', views.records, name='records'),
    path('records/export.csv', views.export_all_csv, name='export_all_csv'),
    path('jobs/<uuid:job_id>/', views.job_detail, name='job_detail'),
    path('jobs/<uuid:job_id>/export.csv', views.export_job_csv, name='export_job_csv'),
    path('jobs/<uuid:job_id>/export.json', views.export_job_json, name='export_job_json'),
    path('jobs/<uuid:job_id>/usage.csv', views.export_usage_csv, name='export_usage_csv'),
    path('jobs/<uuid:job_id>/save/', views.save_reactions, name='save_reactions'),
    path('jobs/<uuid:job_id>/discard/', views.discard_draft, name='discard_draft'),
    path('documents/<int:document_id>/pdf/', views.pdf_document, name='pdf_document'),
    path('documents/<int:document_id>/text/', views.extracted_text_document, name='extracted_text_document'),
    path('documents/<int:document_id>/page/<int:page_number>/image/', views.pdf_page_image, name='pdf_page_image'),
    path('admin/', admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

