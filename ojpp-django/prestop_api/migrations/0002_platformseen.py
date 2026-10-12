from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('prestop_api', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='PlatformSeen',
            fields=[
                ('key', models.CharField(max_length=200, primary_key=True, serialize=False)),
                ('platform', models.CharField(max_length=16)),
                ('destination', models.CharField(default='', max_length=120)),
                ('operator', models.CharField(default='', max_length=80)),
                ('updated', models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
