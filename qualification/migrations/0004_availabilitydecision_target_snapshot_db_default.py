from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('qualification', '0003_availabilitydecision_target_snapshot')]
    operations = [migrations.AlterField(
        model_name='availabilitydecision', name='target_snapshot',
        field=models.JSONField(blank=True, default=dict, db_default={}, editable=False),
    )]
