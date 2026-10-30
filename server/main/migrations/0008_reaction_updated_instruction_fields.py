from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0007_sourcedocument_extracted_text_file'),
    ]

    operations = [
        migrations.AddField(
            model_name='reaction',
            name='reaction_description_type',
            field=models.CharField(default='', max_length=100),
        ),
        migrations.AddField(
            model_name='reaction',
            name='reaction_temperature',
            field=models.CharField(default='', max_length=255),
        ),
        migrations.AddField(
            model_name='reaction',
            name='reaction_yield',
            field=models.CharField(default='', max_length=255),
        ),
    ]
