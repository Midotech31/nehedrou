from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('catalog', '0005_mediaasset_technical_metadata')]
    operations = [
        migrations.AddField(model_name='activity', name='practice_guide', field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name='activity', name='evidence_sources', field=models.JSONField(blank=True, default=list)),
    ]
