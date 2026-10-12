from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='RoadLeg',
            fields=[
                ('key', models.CharField(max_length=64, primary_key=True, serialize=False)),
                ('geometry', models.JSONField(default=list)),
                ('created', models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
