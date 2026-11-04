from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0010_aitokenusage_duration_ms'),
    ]

    operations = [
        migrations.AddField(
            model_name='reaction',
            name='stage_details',
            field=models.JSONField(default=list),
        ),
    ]
