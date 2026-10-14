from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('prestop_push', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='watch',
            name='journey_state',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
