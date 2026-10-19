from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('prestop_push', '0002_watch_journey_state'),
    ]

    operations = [
        migrations.AddField(
            model_name='watch',
            name='exit_stop_id',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
    ]
