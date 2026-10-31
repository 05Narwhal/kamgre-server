# Spec 2026-10-31 H6: staying on the train (train_stays.py).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('prestop_statistics', '0008_train_day_departure_canceled_replaced'),
    ]

    operations = [
        migrations.CreateModel(
            name='TrainCoverDay',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('day', models.DateField(unique=True)),
                ('trains', models.IntegerField(default=0)),
                ('reported', models.IntegerField(default=0)),
                ('collector_seconds', models.IntegerField(default=0)),
            ],
        ),
        migrations.CreateModel(
            name='TrainLinkDay',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('day', models.DateField()),
                ('from_number', models.CharField(max_length=16)),
                ('to_number', models.CharField(max_length=16)),
                ('station', models.CharField(max_length=200)),
                ('station_name', models.CharField(blank=True, default='', max_length=200)),
                ('arrival', models.IntegerField()),
                ('departure', models.IntegerField()),
                ('from_delay', models.IntegerField(null=True)),
                ('to_delay', models.IntegerField(null=True)),
                ('skipped', models.CharField(blank=True, default='', max_length=16)),
                ('level', models.CharField(blank=True, default='', max_length=6)),
            ],
            options={
                'indexes': [models.Index(fields=['day'], name='prestop_sta_link_day_idx')],
            },
        ),
        migrations.CreateModel(
            name='TrainStay',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('from_number', models.CharField(max_length=16)),
                ('to_number', models.CharField(max_length=16)),
                ('station', models.CharField(max_length=200)),
                ('station_name', models.CharField(blank=True, default='', max_length=200)),
                ('kind', models.CharField(default='continues', max_length=10)),
                ('level', models.CharField(max_length=6)),
                ('arrival', models.IntegerField()),
                ('departure', models.IntegerField()),
                ('slack', models.IntegerField(default=0)),
                ('informative_days', models.SmallIntegerField(default=0)),
                ('agree_days', models.SmallIntegerField(default=0)),
                ('last_seen', models.DateField()),
                ('learned_on', models.DateField()),
            ],
        ),
        migrations.AddConstraint(
            model_name='trainlinkday',
            constraint=models.UniqueConstraint(fields=('day', 'from_number', 'to_number'), name='prestop_train_link_day_unique'),
        ),
        migrations.AddConstraint(
            model_name='trainstay',
            constraint=models.UniqueConstraint(fields=('from_number', 'to_number'), name='prestop_train_stay_unique'),
        ),
    ]
