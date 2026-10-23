from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('prestop_push', '0003_watch_exit_stop'),
    ]

    operations = [
        migrations.AddField(
            model_name='watch',
            name='stay_trip_ids',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
