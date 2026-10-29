import secrets

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

LOBBY, QUESTION, RESULTS, FINISHED = "lobby", "question", "results", "finished"
TIME_CHOICES = [(10, "10 сек"), (20, "20 сек"), (30, "30 сек"), (60, "60 сек")]


def new_pin():
    return "".join(secrets.choice("0123456789") for _ in range(6))


class Quiz(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="quizzes")
    title = models.CharField(max_length=100)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return self.title


class Question(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    order = models.PositiveSmallIntegerField(default=0)
    text = models.CharField(max_length=200)
    option_1 = models.CharField(max_length=100)
    option_2 = models.CharField(max_length=100)
    option_3 = models.CharField(max_length=100, blank=True)
    option_4 = models.CharField(max_length=100, blank=True)
    correct = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(4)])
    time_limit = models.PositiveSmallIntegerField(choices=TIME_CHOICES, default=20)

    class Meta:
        ordering = ["order", "id"]

    def option_slots(self):
        """[(слот 1..4, текст)] только для заполненных вариантов."""
        raw = [self.option_1, self.option_2, self.option_3, self.option_4]
        return [(i + 1, t) for i, t in enumerate(raw) if t]


class Game(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="games")
    host = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="games")
    pin = models.CharField(max_length=6, unique=True, default=new_pin)
    state = models.CharField(max_length=10, default=LOBBY)
    current = models.IntegerField(default=-1)
    question_started = models.DateTimeField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    def questions(self):
        if not hasattr(self, "_qs"):
            self._qs = list(self.quiz.questions.all())
        return self._qs

    def current_question(self):
        qs = self.questions()
        return qs[self.current] if 0 <= self.current < len(qs) else None

    def seconds_left(self):
        q = self.current_question()
        if not q or not self.question_started:
            return 0.0
        elapsed = (timezone.now() - self.question_started).total_seconds()
        return max(0.0, q.time_limit - elapsed)


class Player(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="players")
    nickname = models.CharField(max_length=20)
    score = models.IntegerField(default=0)
    joined = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(models.functions.Lower("nickname"), "game", name="uniq_nick_per_game")]


class Answer(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    slot = models.PositiveSmallIntegerField()
    correct = models.BooleanField()
    points = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["player", "question"], name="one_answer_per_question")]
