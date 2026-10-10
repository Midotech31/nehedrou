from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import RateWindow

class Command(BaseCommand):
    help = 'Delete obsolete technical rate-limit buckets; no clinical records are deleted.'
    def handle(self, *args, **kwargs):
        count, _ = RateWindow.objects.filter(created_at__lt=timezone.now() - timedelta(days=1)).delete()
        self.stdout.write(f'{count} obsolete buckets deleted.')
