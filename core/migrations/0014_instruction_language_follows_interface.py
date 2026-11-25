from django.conf import settings
from django.db import migrations, models


def follow_interface_for_demo_families(apps, schema_editor):
    if not settings.DEMO_MODE:
        return
    alias = schema_editor.connection.alias
    User = apps.get_model('core', 'User')
    FamilyLink = apps.get_model('care', 'FamilyLink')
    Membership = apps.get_model('core', 'Membership')
    for username, practice_name in (
        ('famille', 'Cabinet Démonstration'),
        ('accompagnant', 'Cabinet Parcours des rôles · fictif'),
    ):
        users = User.objects.using(alias).filter(
            username=username, email__iexact=f'{username}@demo.example',
            instruction_language='fr', is_staff=False, is_superuser=False,
        )
        links = FamilyLink.objects.using(alias).filter(user__in=users)
        fictional_links = links.filter(
            child__organization__name=practice_name, child__code__endswith='· fictif',
        )
        users.filter(pk__in=fictional_links.values('user_id')).exclude(
            pk__in=links.exclude(pk__in=fictional_links).values('user_id'),
        ).exclude(
            pk__in=Membership.objects.using(alias).values('user_id'),
        ).update(instruction_language_follows_interface=True)


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0013_invoice_shared_with_practice_at'),
        ('care', '0010_program_practice_days_program_practice_end_and_more'),
    ]
    operations = [
        migrations.AddField(
            model_name='user',
            name='instruction_language_follows_interface',
            field=models.BooleanField(default=False, verbose_name='Use the interface language for caregiver instructions'),
        ),
        migrations.RunPython(follow_interface_for_demo_families, migrations.RunPython.noop),
    ]
