from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0009_invitation_manual_handoff')]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='data_notice_contact_email',
            field=models.EmailField(blank=True, max_length=254),
        ),
    ]
