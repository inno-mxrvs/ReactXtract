from django.contrib import admin

from .models import AITokenUsage, ExtractionJob, Reaction, SourceDocument


admin.site.register(ExtractionJob)
admin.site.register(SourceDocument)
admin.site.register(Reaction)
admin.site.register(AITokenUsage)

