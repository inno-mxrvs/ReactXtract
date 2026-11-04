from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0011_reaction_stage_details'),
    ]

    operations = [
        migrations.AddField(
            model_name='aitokenusage',
            name='attempt_number',
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name='aitokenusage',
            name='error_message',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='aitokenusage',
            name='error_type',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name='aitokenusage',
            name='reasoning_tokens',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='aitokenusage',
            name='status',
            field=models.CharField(
                choices=[
                    ('completed', 'Completed'),
                    ('timeout', 'Timed out'),
                    ('failed', 'Failed'),
                ],
                default='completed',
                max_length=20,
            ),
        ),
    ]
