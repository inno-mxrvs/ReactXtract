from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0006_extractionjob_discard_requested'),
    ]

    operations = [
        migrations.AddField(
            model_name='sourcedocument',
            name='extracted_text_file',
            field=models.FileField(blank=True, upload_to='extracted_text/%Y/%m/%d/'),
        ),
    ]
