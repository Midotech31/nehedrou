from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('catalog', '0002_initial')]
    operations = [migrations.AddField(model_name='review', name='content_digest', field=models.CharField(max_length=64, editable=False, default=''), preserve_default=False)]
