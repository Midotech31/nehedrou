import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('catalog', '0016_mediauploadreceipt')]

    operations = [
        migrations.AddField(
            model_name='mediaasset',
            name='image_predecessor',
            field=models.ForeignKey(blank=True, editable=False, null=True, related_name='+',
                on_delete=django.db.models.deletion.PROTECT, to='catalog.mediaasset'),
        ),
    ]
