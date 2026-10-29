from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from game.models import Game


class Command(BaseCommand):
    help = "Удаляет игры старше N часов (по умолчанию 24) вместе с игроками и ответами."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=24)

    def handle(self, *args, **opts):
        n, _ = Game.objects.filter(created__lt=timezone.now() - timedelta(hours=opts["hours"])).delete()
        self.stdout.write(f"Удалено объектов: {n}")
