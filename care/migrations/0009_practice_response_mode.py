from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('care', '0008_practice_support')]

    operations = [
        migrations.AddField(
            model_name='practicesession', name='response_mode',
            field=models.CharField(max_length=12, default='matching', choices=[('matching', 'Matching picture'), ('free', 'Free picture choice'), ('observation', 'Shared observation')]),
        ),
    ]