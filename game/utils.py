import base64
import io
from functools import wraps

import qrcode
import qrcode.image.svg
from django.core.cache import cache
from django.http import HttpResponse
from django.utils import timezone

from .models import QUESTION, RESULTS


def client_ip(request):
    # X-Forwarded-For is client-controlled unless every proxy in the chain is
    # configured to sanitize it. Do not use it for security decisions such as
    # rate limiting; TRUST_PROXY is only for Django's HTTPS detection.
    return request.META.get("REMOTE_ADDR", "")


def throttle(scope, limit, window):
    """Простой лимит POST-запросов на IP (кэш процесса; для нескольких воркеров — Redis)."""
    def deco(view):
        @wraps(view)
        def wrapper(request, *a, **kw):
            if request.method == "POST":
                key = f"thr:{scope}:{client_ip(request)}"
                cache.add(key, 0, window)
                try:
                    n = cache.incr(key)
                except ValueError:
                    cache.set(key, 1, window)
                    n = 1
                if n > limit:
                    return HttpResponse("Слишком много запросов, подождите минуту.", status=429)
            return view(request, *a, **kw)
        return wrapper
    return deco


def qr_data_uri(text):
    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


def sync(game):
    """Автоматически закрывает вопрос по таймеру или когда ответили все."""
    if game.state != QUESTION:
        return
    from .models import Answer
    q = game.current_question()
    if q is None:
        game.state = RESULTS
        game.save(update_fields=["state"])
        return
    total = game.players.count()
    answered = Answer.objects.filter(question=q, player__game=game).count()
    if game.seconds_left() <= 0 or (total and answered >= total):
        game.state = RESULTS
        game.save(update_fields=["state"])


def points_for(game, question):
    left = game.seconds_left()
    ratio = left / question.time_limit
    return round(500 + 500 * ratio)  # 500..1000


def now():
    return timezone.now()
