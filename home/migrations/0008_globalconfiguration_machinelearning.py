from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0007_remove_globalconfiguration_datalake'),
    ]

    operations = [
        migrations.AddField(
            model_name='globalconfiguration',
            name='machineLearning',
            field=models.BooleanField(default=True),
        ),
    ]
