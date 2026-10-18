from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('prestop_statistics', '0005_stays'),
    ]

    operations = [
        migrations.AddField(
            model_name='vehicletrip',
            name='dwell',
            field=models.JSONField(default=dict),
        ),
        migrations.CreateModel(
            name='LearnedTime',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('route_id', models.CharField(max_length=200)),
                ('kind', models.CharField(max_length=8)),
                ('band', models.CharField(max_length=5)),
                ('segments', models.JSONField(default=dict)),
                ('dwells', models.JSONField(default=dict)),
                ('learned_on', models.DateField()),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('route_id', 'kind', 'band'), name='prestop_learned_time_unique')],
            },
        ),
    ]
