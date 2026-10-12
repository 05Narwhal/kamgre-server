from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('prestop_statistics', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='tripdelay',
            name='segments',
            field=models.JSONField(default=dict),
        ),
    ]
