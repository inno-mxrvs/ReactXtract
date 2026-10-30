from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0005_blank_unreported_reaction_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='extractionjob',
            name='discard_requested',
            field=models.BooleanField(default=False),
        ),
    ]
