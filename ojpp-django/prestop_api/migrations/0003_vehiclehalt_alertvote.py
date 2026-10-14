from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('prestop_api', '0002_platformseen'),
    ]

    operations = [
        migrations.CreateModel(
            name='VehicleHalt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('vehicle_id', models.CharField(max_length=200)),
                ('trip_id', models.CharField(max_length=200)),
                ('route_id', models.CharField(max_length=200)),
                ('stop_id', models.CharField(max_length=200)),
                ('latitude', models.FloatField()),
                ('longitude', models.FloatField()),
                ('since', models.DateTimeField()),
                ('last_seen', models.DateTimeField()),
                ('cleared', models.DateTimeField(null=True)),
            ],
            options={'indexes': [models.Index(fields=['cleared', 'last_seen'], name='prestop_api_halt_open_idx')]},
        ),
        migrations.CreateModel(
            name='AlertVote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('alert_id', models.CharField(max_length=120)),
                ('device', models.CharField(max_length=64)),
                ('ip', models.CharField(max_length=64)),
                ('vote', models.BooleanField()),
                ('created', models.DateTimeField()),
            ],
            options={
                'indexes': [models.Index(fields=['ip', 'created'], name='prestop_api_vote_ip_idx')],
                'constraints': [models.UniqueConstraint(fields=('alert_id', 'device'), name='prestop_alert_vote_unique')],
            },
        ),
    ]
