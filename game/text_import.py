import re


MAX_IMPORT_CHARS = 30_000
MAX_IMPORT_QUESTIONS = 50
FIELD_LIMITS = {"question": 200, "answer": 100}
LABEL_RE = re.compile(r"^\[(вопрос|ответ|правильный ответ)\]\s*(.*)$", re.IGNORECASE)


def parse_question_text(raw_text):
    """Parse labeled AI-generated text without creating or changing any records."""
    if not isinstance(raw_text, str):
        return [], ["Вставьте текст с вопросами."]
    if len(raw_text) > MAX_IMPORT_CHARS:
        return [], [f"Текст слишком большой: максимум {MAX_IMPORT_CHARS} символов."]

    blocks = []
    errors = []
    current = None
    question_count = 0

    def finish_block():
        if current is None:
            return
        number = current["number"]
        question = current["question"]
        if not question:
            errors.append(f"Вопрос {number}, строка {current['line']}: текст вопроса пуст.")
        elif len(question) > FIELD_LIMITS["question"]:
            errors.append(f"Вопрос {number}, строка {current['line']}: максимум {FIELD_LIMITS['question']} символов.")

        choices = current["answers"]
        if not 2 <= len(choices) <= 4:
            errors.append(f"Вопрос {number}: нужно указать от 2 до 4 строк [ответ].")
        if len(current["correct"]) != 1:
            errors.append(f"Вопрос {number}: укажите ровно одну строку [правильный ответ].")

        answer_texts = [text for _, text in choices]
        if any(not text for _, text in choices):
            errors.append(f"Вопрос {number}: текст каждого ответа должен быть заполнен.")
        if any(len(text) > FIELD_LIMITS["answer"] for _, text in choices):
            errors.append(f"Вопрос {number}: длина каждого ответа — максимум {FIELD_LIMITS['answer']} символов.")
        normalized = [text.casefold() for text in answer_texts]
        if len(set(normalized)) != len(normalized):
            errors.append(f"Вопрос {number}: варианты ответов должны отличаться.")
        valid_choices = (
            2 <= len(choices) <= 4
            and all(answer_texts)
            and all(len(text) <= FIELD_LIMITS["answer"] for text in answer_texts)
            and len(set(normalized)) == len(normalized)
        )
        valid_question = bool(question) and len(question) <= FIELD_LIMITS["question"]

        if len(current["correct"]) == 1:
            correct_text = current["correct"][0]
            valid_correct = bool(correct_text) and len(correct_text) <= FIELD_LIMITS["answer"]
            if not correct_text:
                errors.append(f"Вопрос {number}: текст правильного ответа должен быть заполнен.")
            if len(correct_text) > FIELD_LIMITS["answer"]:
                errors.append(f"Вопрос {number}: длина правильного ответа — максимум {FIELD_LIMITS['answer']} символов.")
            matches = [index for index, text in enumerate(answer_texts) if text.casefold() == correct_text.casefold()]
            if len(matches) != 1:
                errors.append(f"Вопрос {number}: правильный ответ должен совпадать с одним из вариантов ответа.")
            elif valid_correct and valid_question and valid_choices:
                blocks.append({
                    "text": question,
                    "option_1": answer_texts[0],
                    "option_2": answer_texts[1],
                    "option_3": answer_texts[2] if len(answer_texts) > 2 else "",
                    "option_4": answer_texts[3] if len(answer_texts) > 3 else "",
                    "correct": matches[0] + 1,
                    "time_limit": 20,
                })
        elif question and not choices:
            # The answer-count error above is sufficient; do not expose an incomplete block.
            pass

    for line_number, original in enumerate(raw_text.splitlines(), start=1):
        line = original.strip()
        if not line:
            continue
        match = LABEL_RE.fullmatch(line)
        if not match:
            # AI answers may include a short preamble before the first formatted question.
            if current is None and question_count == 0:
                continue
            errors.append(f"Строка {line_number}: ожидается [вопрос], [ответ] или [правильный ответ].")
            continue

        label, value = match.groups()
        label = label.casefold()
        if label == "вопрос":
            finish_block()
            if question_count >= MAX_IMPORT_QUESTIONS:
                errors.append(f"Можно импортировать не более {MAX_IMPORT_QUESTIONS} вопросов за раз.")
                current = None
                break
            question_count += 1
            current = {"number": question_count, "line": line_number, "question": value.strip(), "answers": [], "correct": []}
            continue

        if current is None:
            errors.append(f"Строка {line_number}: сначала добавьте строку [вопрос].")
            continue
        value = value.strip()
        if label == "правильный ответ":
            current["correct"].append(value)
        else:
            current["answers"].append((label, value))

    finish_block()
    if not blocks and not errors:
        errors.append("Не найдено ни одного вопроса.")
    return blocks, errors
