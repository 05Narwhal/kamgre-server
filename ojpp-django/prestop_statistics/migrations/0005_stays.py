from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('prestop_statistics', '0004_vehicle_gaps'),
    ]

    operations = [
        migrations.CreateModel(
            name='StayDeparture',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(max_length=8)),
                ('feed', models.CharField(max_length=64)),
                ('route_id', models.CharField(max_length=200)),
                ('start', models.IntegerField()),
                ('pattern', models.CharField(max_length=16)),
                ('origin', models.CharField(max_length=10)),
                ('level', models.CharField(blank=True, default='', max_length=6)),
                ('prev_route_id', models.CharField(blank=True, default='', max_length=200)),
                ('prev_start', models.IntegerField(null=True)),
                ('prev_pattern', models.CharField(blank=True, default='', max_length=16)),
                ('prev_end', models.IntegerField(null=True)),
                ('days', models.SmallIntegerField(default=0)),
                ('share', models.FloatField(default=0)),
                ('absorb', models.IntegerField(null=True)),
                ('depot_delay', models.IntegerField(null=True)),
                ('learned_on', models.DateField()),
            ],
            options={'constraints': [models.UniqueConstraint(fields=('kind', 'route_id', 'start'), name='prestop_stay_departure_unique')]},
        ),
        migrations.CreateModel(
            name='StayCheck',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('day', models.DateField()),
                ('feed', models.CharField(max_length=64)),
                ('level', models.CharField(max_length=6)),
                ('hits', models.IntegerField(default=0)),
                ('misses', models.IntegerField(default=0)),
            ],
            options={'constraints': [models.UniqueConstraint(fields=('day', 'feed', 'level'), name='prestop_stay_check_unique')]},
        ),
    ]
