import json

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.views import LoginView
from django.db import IntegrityError, transaction
from django.db.models import F
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .forms import NicknameForm, PinForm, QuestionForm, QuizForm
from .models import FINISHED, LOBBY, QUESTION, RESULTS, Answer, Game, Player, Quiz
from .utils import points_for, qr_data_uri, sync, throttle


# ---------- общие ----------
@throttle("home", 60, 60)
def home(request):
    form = PinForm(request.POST or None)
    error = None
    if request.method == "POST" and form.is_valid():
        pin = form.cleaned_data["pin"]
        if Game.objects.filter(pin=pin).exists():
            return redirect("join", pin=pin)
        error = "Игра с таким PIN не найдена"
    return render(request, "game/home.html", {"form": form, "error": error})


@throttle("signup", 10, 3600)
def signup(request):
    if not settings.ALLOW_SIGNUP:
        raise Http404
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("dashboard")
    return render(request, "registration/signup.html", {"form": form})


@method_decorator(throttle("login", 15, 60), name="dispatch")
class RateLimitedLogin(LoginView):
    pass


# ---------- ведущий: квизы ----------
@login_required
def dashboard(request):
    quizzes = request.user.quizzes.all()
    form = QuizForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if quizzes.count() >= settings.MAX_QUIZZES_PER_USER:
            form.add_error(None, "Достигнут лимит квизов")
        else:
            quiz = form.save(commit=False)
            quiz.owner = request.user
            quiz.save()
            return redirect("quiz_detail", pk=quiz.pk)
    return render(request, "game/dashboard.html", {"quizzes": quizzes, "form": form})


def _own_quiz(request, pk):
    return get_object_or_404(Quiz, pk=pk, owner=request.user)


@login_required
def quiz_detail(request, pk):
    quiz = _own_quiz(request, pk)
    form = QuestionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if quiz.questions.count() >= settings.MAX_QUESTIONS_PER_QUIZ:
            form.add_error(None, "Достигнут лимит вопросов")
        else:
            q = form.save(commit=False)
            q.quiz = quiz
            q.order = quiz.questions.count() + 1
            q.save()
            return redirect("quiz_detail", pk=quiz.pk)
    return render(request, "game/quiz_detail.html", {"quiz": quiz, "questions": quiz.questions.all(), "form": form})


@login_required
@require_POST
def quiz_delete(request, pk):
    _own_quiz(request, pk).delete()
    return redirect("dashboard")


@login_required
@require_POST
def question_delete(request, pk, qpk):
    quiz = _own_quiz(request, pk)
    get_object_or_404(quiz.questions, pk=qpk).delete()
    return redirect("quiz_detail", pk=pk)


@login_required
@require_POST
def quiz_start(request, pk):
    quiz = _own_quiz(request, pk)
    if not quiz.questions.exists():
        return redirect("quiz_detail", pk=pk)
    for _ in range(10):  # защита от редкой коллизии PIN
        try:
            with transaction.atomic():
                game = Game.objects.create(quiz=quiz, host=request.user)
            return redirect("host", pin=game.pin)
        except IntegrityError:
            continue
    raise Http404


# ---------- ведущий: игра ----------
def _host_game(request, pin):
    return get_object_or_404(Game.objects.select_related("quiz"), pin=pin, host=request.user)


@login_required
def host_game(request, pin):
    game = _host_game(request, pin)
    base = settings.PUBLIC_BASE_URL or request.build_absolute_uri("/").rstrip("/")
    join_url = base + reverse("join", kwargs={"pin": game.pin})
    return render(request, "game/host.html", {
        "game": game, "join_url": join_url, "qr": qr_data_uri(join_url),
        "state_url": reverse("host_state", kwargs={"pin": pin}),
        "action_url": reverse("host_action", kwargs={"pin": pin}),
    })


def _host_payload(game):
    sync(game)
    players = list(game.players.order_by("-score", "joined"))
    data = {
        "phase": game.state, "total": len(game.questions()),
        "players": [{"nickname": p.nickname, "score": p.score} for p in players],
    }
    q = game.current_question()
    if game.state in (QUESTION, RESULTS) and q:
        answers = Answer.objects.filter(question=q, player__game=game)
        data["question"] = {
            "index": game.current + 1, "text": q.text, "time_left": game.seconds_left(),
            "options": [{"slot": s, "text": t} for s, t in q.option_slots()],
            "answered": answers.count(),
        }
        if game.state == RESULTS:
            counts = {s: 0 for s, _ in q.option_slots()}
            for a in answers:
                counts[a.slot] = counts.get(a.slot, 0) + 1
            data["question"]["counts"] = counts
            data["question"]["correct"] = q.correct
    return data


@login_required
@require_GET
@never_cache
def host_state(request, pin):
    return JsonResponse(_host_payload(_host_game(request, pin)))


@login_required
@require_POST
def host_action(request, pin):
    game = _host_game(request, pin)
    try:
        expected = json.loads(request.body or b"{}").get("from")
    except (ValueError, AttributeError):
        return JsonResponse({"error": "bad request"}, status=400)
    with transaction.atomic():
        game = Game.objects.select_for_update().select_related("quiz").get(pk=game.pk)
        sync(game)
        if expected == game.state:  # идемпотентность при двойном клике
            from .utils import now
            n = len(game.questions())
            if game.state == LOBBY:
                if not game.players.exists():
                    return JsonResponse({"error": "Нет игроков"}, status=400)
                game.current, game.state, game.question_started = 0, QUESTION, now()
            elif game.state == QUESTION:
                game.state = RESULTS
            elif game.state == RESULTS:
                if game.current + 1 < n:
                    game.current, game.state, game.question_started = game.current + 1, QUESTION, now()
                else:
                    game.state = FINISHED
            game.save()
    return JsonResponse(_host_payload(game))


# ---------- игрок ----------
def get_player(request, game):
    pid = request.session.get("players", {}).get(game.pin)
    return Player.objects.filter(pk=pid, game=game).first() if pid else None


@throttle("join", 60, 60)
def join(request, pin):
    game = Game.objects.filter(pin=pin).first()
    if game is None:
        raise Http404
    if get_player(request, game):
        return redirect("play", pin=pin)
    form = NicknameForm(request.POST or None)
    error = None
    if game.state != LOBBY:
        error = "Игра уже началась"
    elif request.method == "POST" and form.is_valid():
        nick = form.cleaned_data["nickname"]
        if game.players.count() >= settings.MAX_PLAYERS_PER_GAME:
            error = "Комната заполнена"
        else:
            try:
                with transaction.atomic():
                    player = Player.objects.create(game=game, nickname=nick)
            except IntegrityError:
                form.add_error("nickname", "Этот ник уже занят")
            else:
                players = request.session.get("players", {})
                players[game.pin] = player.pk
                request.session["players"] = players
                return redirect("play", pin=pin)
    return render(request, "game/join.html", {"form": form, "error": error, "pin": pin})


def play(request, pin):
    game = get_object_or_404(Game, pin=pin)
    player = get_player(request, game)
    if not player:
        return redirect("join", pin=pin)
    return render(request, "game/play.html", {
        "game": game, "player": player,
        "state_url": reverse("play_state", kwargs={"pin": pin}),
        "answer_url": reverse("play_answer", kwargs={"pin": pin}),
    })


@require_GET
@never_cache
def play_state(request, pin):
    game = get_object_or_404(Game.objects.select_related("quiz"), pin=pin)
    player = get_player(request, game)
    if not player:
        return JsonResponse({"error": "not joined"}, status=403)
    sync(game)
    ranking = list(game.players.order_by("-score", "joined").values_list("pk", flat=True))
    player.refresh_from_db()
    data = {"phase": game.state, "nickname": player.nickname, "score": player.score,
            "rank": ranking.index(player.pk) + 1, "players": len(ranking), "total": len(game.questions())}
    q = game.current_question()
    if game.state in (QUESTION, RESULTS) and q:
        mine = Answer.objects.filter(player=player, question=q).first()
        data["question"] = {
            "index": game.current + 1, "text": q.text, "time_left": game.seconds_left(),
            "options": [{"slot": s, "text": t} for s, t in q.option_slots()],
            "answered": mine.slot if mine else None,
        }
        if game.state == RESULTS:  # правильный ответ раскрывается только после закрытия вопроса
            data["question"]["correct"] = q.correct
            data["question"]["my_correct"] = bool(mine and mine.correct)
            data["question"]["my_points"] = mine.points if mine else 0
    return JsonResponse(data)


@require_POST
@throttle("answer", 600, 60)
def play_answer(request, pin):
    game = get_object_or_404(Game, pin=pin)
    player = get_player(request, game)
    if not player:
        return JsonResponse({"error": "not joined"}, status=403)
    try:
        slot = int(json.loads(request.body)["slot"])
    except (ValueError, TypeError, KeyError, OverflowError):
        return JsonResponse({"error": "bad request"}, status=400)
    with transaction.atomic():
        game = Game.objects.select_for_update().select_related("quiz").get(pk=game.pk)
        sync(game)
        q = game.current_question()
        if game.state != QUESTION or q is None:
            return JsonResponse({"error": "closed"}, status=409)
        if slot not in dict(q.option_slots()):
            return JsonResponse({"error": "bad slot"}, status=400)
        correct = slot == q.correct
        points = points_for(game, q) if correct else 0
        try:
            with transaction.atomic():
                Answer.objects.create(player=player, question=q, slot=slot, correct=correct, points=points)
        except IntegrityError:
            return JsonResponse({"error": "already answered"}, status=409)
        if points:
            Player.objects.filter(pk=player.pk).update(score=F("score") + points)
    return JsonResponse({"ok": True})
