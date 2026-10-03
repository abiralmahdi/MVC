from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0011_usermodel_raw_password'),
    ]

    operations = [
        migrations.AddField(
            model_name='usermodel',
            name='phone',
            field=models.CharField(blank=True, default='', max_length=32),
        ),
    ]
