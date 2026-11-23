from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0008_processingactivityrevision')]

    operations = [
        migrations.AlterField(
            model_name='invitation',
            name='delivery',
            field=models.CharField(max_length=12, default='pending', choices=[
                ('pending', 'Pending delivery'), ('sent', 'Sent to mail service'),
                ('failed', 'Delivery failed'), ('console', 'Local console only'),
                ('manual', 'Link created for manual handoff'),
            ]),
        ),
    ]
