from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0004_alter_extractionjob_status'),
    ]

    operations = [
        migrations.AlterField(
            model_name='reaction',
            name='other_conditions',
            field=models.TextField(default=''),
        ),
        migrations.AlterField(
            model_name='reaction',
            name='reaction_pressure',
            field=models.CharField(default='', max_length=255),
        ),
        migrations.AlterField(
            model_name='reaction',
            name='reaction_stages',
            field=models.CharField(default='', max_length=100),
        ),
        migrations.AlterField(
            model_name='reaction',
            name='reaction_time',
            field=models.CharField(default='', max_length=255),
        ),
    ]
