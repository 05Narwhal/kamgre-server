from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('prestop_statistics', '0011_bus_statistics'),
    ]

    operations = [
        migrations.AddField(
            model_name='traincoverday',
            name='unreported',
            field=models.IntegerField(null=True, default=None),
        ),
    ]
