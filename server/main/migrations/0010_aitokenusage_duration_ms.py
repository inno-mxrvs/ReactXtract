from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0009_extractionjob_total_duration_ms'),
    ]

    operations = [
        migrations.AddField(
            model_name='aitokenusage',
            name='duration_ms',
            field=models.PositiveBigIntegerField(default=0),
        ),
    ]
