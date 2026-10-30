import uuid

from django.db import models


class ExtractionJob(models.Model):
    class Status(models.TextChoices):
        PROCESSING = 'processing', 'Processing'
        DRAFT = 'draft', 'Unsaved draft'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROCESSING)
    model_name = models.CharField(max_length=120, blank=True)
    error_message = models.TextField(blank=True)
    reaction_count = models.PositiveIntegerField(default=0)
    total_prompt_tokens = models.PositiveIntegerField(default=0)
    total_completion_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    estimated_cost_usd = models.DecimalField(max_digits=14, decimal_places=6, default=0)
    processing_duration_ms = models.PositiveBigIntegerField(default=0)
    discard_requested = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class SourceDocument(models.Model):
    job = models.ForeignKey(ExtractionJob, on_delete=models.CASCADE, related_name='documents')
    original_name = models.CharField(max_length=255)
    file = models.FileField(upload_to='uploads/%Y/%m/%d/')
    extracted_text_file = models.FileField(upload_to='extracted_text/%Y/%m/%d/', blank=True)
    page_count = models.PositiveIntegerField(default=0)
    file_size = models.PositiveBigIntegerField(default=0)
    selected_pages = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return self.original_name


class Reaction(models.Model):
    job = models.ForeignKey(ExtractionJob, on_delete=models.CASCADE, related_name='reactions')
    reaction_number = models.PositiveIntegerField()
    products = models.JSONField(default=list)
    starting_materials = models.JSONField(default=list)
    reagents = models.JSONField(default=list)
    catalysts = models.JSONField(default=list)
    solvents = models.JSONField(default=list)
    reaction_time = models.CharField(max_length=255, default='')
    reaction_pressure = models.CharField(max_length=255, default='')
    reaction_temperature = models.CharField(max_length=255, default='')
    other_conditions = models.TextField(default='')
    reaction_stages = models.CharField(max_length=100, default='')
    reaction_description_type = models.CharField(max_length=100, default='')
    reaction_yield = models.CharField(max_length=255, default='')
    source_evidence = models.JSONField(default=list)
    confidence_scores = models.JSONField(default=dict)
    field_evidence = models.JSONField(default=dict)
    reviewer_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['reaction_number']
        constraints = [models.UniqueConstraint(fields=['job', 'reaction_number'], name='unique_job_reaction_number')]

    def __str__(self):
        return f'{self.job.title} — reaction {self.reaction_number}'


class AITokenUsage(models.Model):
    class Phase(models.TextChoices):
        EXTRACTION = 'extraction', 'Extraction'
        CONSOLIDATION = 'consolidation', 'Consolidation'

    job = models.ForeignKey(ExtractionJob, on_delete=models.CASCADE, related_name='token_usages')
    document = models.ForeignKey(SourceDocument, on_delete=models.SET_NULL, null=True, blank=True, related_name='token_usages')
    phase = models.CharField(max_length=20, choices=Phase.choices)
    chunk_number = models.PositiveIntegerField(default=1)
    model_name = models.CharField(max_length=120)
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    estimated_cost_usd = models.DecimalField(max_digits=14, decimal_places=6, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

