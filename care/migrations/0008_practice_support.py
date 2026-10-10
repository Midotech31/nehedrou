from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('care', '0007_programfeedback')]
    operations = [
        migrations.AddField(model_name='practicesession', name='support_used', field=models.CharField(blank=True, default='', max_length=20, choices=[('', 'Not recorded'), ('none', 'No support reported'), ('model', 'Clinician-taught word model'), ('gesture', 'Gesture'), ('instructions', 'Repeated instructions'), ('multiple', 'Several supports'), ('unsure', 'Unsure about the support')])),
        migrations.AddField(model_name='practicesession', name='stop_reason', field=models.CharField(blank=True, default='', max_length=20, choices=[('', 'Not recorded'), ('fatigue', 'Fatigue'), ('upset', 'Upset'), ('understanding', 'Task not understood'), ('other', 'Another reason')])),
    ]
