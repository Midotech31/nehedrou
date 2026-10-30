from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('qualification', '0002_evidencedocument_valid_from_and_more')]
    operations = [migrations.AddField(
        model_name='availabilitydecision', name='target_snapshot',
        field=models.JSONField(blank=True, default=dict, editable=False),
    )]
