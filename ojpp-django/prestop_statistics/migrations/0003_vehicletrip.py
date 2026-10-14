from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('prestop_statistics', '0002_tripdelay_segments'),
    ]

    operations = [
        migrations.CreateModel(
            name='VehicleTrip',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('service_date', models.DateField()),
                ('trip_id', models.CharField(max_length=200)),
                ('vehicle_id', models.CharField(max_length=200)),
                ('route_id', models.CharField(max_length=200)),
                ('block_id', models.CharField(blank=True, default='', max_length=200)),
                ('start', models.IntegerField()),
                ('end', models.IntegerField()),
                ('end_delay', models.IntegerField(null=True)),
                ('first_seen', models.DateTimeField()),
                ('last_seen', models.DateTimeField()),
            ],
            options={
                'indexes': [models.Index(fields=['route_id', 'service_date'], name='prestop_sta_route_i_7c1f2a_idx'),
                            models.Index(fields=['vehicle_id', 'service_date'], name='prestop_sta_vehicle_3b9e4d_idx')],
                'constraints': [models.UniqueConstraint(fields=('service_date', 'trip_id'), name='prestop_vehicle_trip_unique')],
            },
        ),
    ]
