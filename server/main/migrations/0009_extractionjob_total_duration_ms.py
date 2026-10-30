from django.db import migrations, models


def backfill_total_duration(apps, schema_editor):
    ExtractionJob = apps.get_model('main', 'ExtractionJob')
    for job in ExtractionJob.objects.exclude(completed_at=None).iterator():
        elapsed_ms = max(
            0,
            round((job.completed_at - job.created_at).total_seconds() * 1000),
        )
        ExtractionJob.objects.filter(pk=job.pk).update(total_duration_ms=elapsed_ms)


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0008_reaction_updated_instruction_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='extractionjob',
            name='total_duration_ms',
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.RunPython(backfill_total_duration, migrations.RunPython.noop),
    ]
