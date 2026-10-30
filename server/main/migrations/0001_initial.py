import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name='ExtractionJob',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('title', models.CharField(max_length=255)),
                ('status', models.CharField(choices=[('processing', 'Processing'), ('completed', 'Completed'), ('failed', 'Failed')], default='processing', max_length=20)),
                ('model_name', models.CharField(blank=True, max_length=120)),
                ('error_message', models.TextField(blank=True)),
                ('reaction_count', models.PositiveIntegerField(default=0)),
                ('total_prompt_tokens', models.PositiveIntegerField(default=0)),
                ('total_completion_tokens', models.PositiveIntegerField(default=0)),
                ('total_tokens', models.PositiveIntegerField(default=0)),
                ('estimated_cost_usd', models.DecimalField(decimal_places=6, default=0, max_digits=14)),
                ('processing_duration_ms', models.PositiveBigIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='SourceDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('original_name', models.CharField(max_length=255)),
                ('file', models.FileField(upload_to='uploads/%Y/%m/%d/')),
                ('ocr_text_file', models.FileField(blank=True, upload_to='ocr/%Y/%m/%d/')),
                ('page_count', models.PositiveIntegerField(default=0)),
                ('character_count', models.PositiveIntegerField(default=0)),
                ('ocr_duration_ms', models.PositiveBigIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('job', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='documents', to='main.extractionjob')),
            ],
            options={'ordering': ['id']},
        ),
        migrations.CreateModel(
            name='Reaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reaction_number', models.PositiveIntegerField()),
                ('products', models.JSONField(default=list)),
                ('starting_materials', models.JSONField(default=list)),
                ('reagents', models.JSONField(default=list)),
                ('catalysts', models.JSONField(default=list)),
                ('solvents', models.JSONField(default=list)),
                ('reaction_time', models.CharField(default='Not reported.', max_length=255)),
                ('reaction_pressure', models.CharField(default='Not reported.', max_length=255)),
                ('other_conditions', models.TextField(default='Not reported.')),
                ('reaction_stages', models.PositiveIntegerField(default=1)),
                ('source_evidence', models.JSONField(default=list)),
                ('reviewer_notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('job', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reactions', to='main.extractionjob')),
            ],
            options={'ordering': ['reaction_number']},
        ),
        migrations.CreateModel(
            name='AITokenUsage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('phase', models.CharField(choices=[('extraction', 'Extraction'), ('consolidation', 'Consolidation')], max_length=20)),
                ('chunk_number', models.PositiveIntegerField(default=1)),
                ('model_name', models.CharField(max_length=120)),
                ('prompt_tokens', models.PositiveIntegerField(default=0)),
                ('completion_tokens', models.PositiveIntegerField(default=0)),
                ('total_tokens', models.PositiveIntegerField(default=0)),
                ('estimated_cost_usd', models.DecimalField(decimal_places=6, default=0, max_digits=14)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('document', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='token_usages', to='main.sourcedocument')),
                ('job', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='token_usages', to='main.extractionjob')),
            ],
            options={'ordering': ['created_at']},
        ),
        migrations.AddConstraint(
            model_name='reaction',
            constraint=models.UniqueConstraint(fields=('job', 'reaction_number'), name='unique_job_reaction_number'),
        ),
    ]
