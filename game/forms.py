import re

from django import forms

from .models import Question, Quiz

NICK_RE = re.compile(r"^[\w .\-]{2,20}$")


class QuizForm(forms.ModelForm):
    class Meta:
        model = Quiz
        fields = ["title"]
        labels = {"title": "Название квиза"}


class QuestionForm(forms.ModelForm):
    correct = forms.TypedChoiceField(
        choices=[(1, "Вариант 1 (красный)"), (2, "Вариант 2 (синий)"), (3, "Вариант 3 (жёлтый)"), (4, "Вариант 4 (зелёный)")],
        coerce=int, label="Правильный ответ")

    class Meta:
        model = Question
        fields = ["text", "option_1", "option_2", "option_3", "option_4", "correct", "time_limit"]
        labels = {"text": "Вопрос", "option_1": "Вариант 1", "option_2": "Вариант 2",
                  "option_3": "Вариант 3 (необязательно)", "option_4": "Вариант 4 (необязательно)",
                  "time_limit": "Время на ответ"}

    def clean(self):
        data = super().clean()
        c = data.get("correct")
        if c and not data.get(f"option_{c}", "").strip():
            self.add_error("correct", "Правильный ответ указывает на пустой вариант")
        if data.get("option_4") and not data.get("option_3"):
            self.add_error("option_3", "Заполните вариант 3 перед вариантом 4")
        return data


class NicknameForm(forms.Form):
    nickname = forms.CharField(max_length=20, label="Ваш ник", strip=True)

    def clean_nickname(self):
        n = self.cleaned_data["nickname"]
        if not NICK_RE.match(n):
            raise forms.ValidationError("2–20 символов: буквы, цифры, пробел, . _ -")
        return n


class PinForm(forms.Form):
    pin = forms.RegexField(r"^\d{6}$", label="PIN игры", error_messages={"invalid": "PIN — 6 цифр"})
