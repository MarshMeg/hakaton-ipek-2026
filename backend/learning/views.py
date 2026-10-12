"""Экраны игры: карта курса, прохождение урока (HTMX), итоги."""

import random
from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.models import Profile
from accounts.services import get_player
from courses.models import Course, Exercise, Lesson

from .services import lesson_engine as engine
from .services.answer_check import UDMURT_TO_PLAIN
from .services.progress import is_lesson_open, lesson_states

UDMURT_KEYS = list(UDMURT_TO_PLAIN)  # ӝ ӟ ӥ ӧ ӵ — кнопки экранной клавиатуры
LEADERBOARD_SIZE = 50
MAX_MATCH_MISTAKES = 20  # счётчик ошибок в «Найди пары» приходит с клиента — ограничиваем


@login_required
def home(request):
    player = get_player(request)
    course = Course.objects.prefetch_related("units__lessons").first()
    units = []
    if course:
        states = lesson_states(player, course.id)
        for unit in course.units.all():
            lessons = [{"obj": lesson} | states[lesson.id] for lesson in unit.lessons.all()]
            units.append({"obj": unit, "lessons": lessons})
    return render(request, "learning/home.html", {"course": course, "units": units})


@login_required
def welcome(request):
    """Правила игры: показываются один раз — сразу после регистрации."""
    get_player(request)
    return render(request, "learning/welcome.html", {"game": settings.GAME})


def open_lesson_required(view):
    """Закрытый урок (не пройден предыдущий) не запускается и по прямой ссылке."""

    @wraps(view)
    def wrapper(request, lesson_id, *args, **kwargs):
        lesson = get_object_or_404(Lesson.objects.select_related("unit"), id=lesson_id)
        if not is_lesson_open(request.user, lesson):
            if request.htmx:
                response = HttpResponse()
                response["HX-Redirect"] = reverse("learning:home")
                return response
            return redirect("learning:home")
        return view(request, lesson_id, *args, **kwargs)

    return wrapper


@login_required
def leaderboard(request):
    """Таблица лидеров по опыту. Старые гостевые аккаунты и игроки без опыта в неё не попадают."""
    player = get_player(request)
    ranked = Profile.objects.filter(is_guest=False, xp__gt=0).select_related("user")
    top = list(ranked.order_by("-xp", "-streak", "user__date_joined")[:LEADERBOARD_SIZE])
    # Место считается по опыту: у игроков с одинаковым опытом оно общее.
    rows, place = [], 0
    for index, entry in enumerate(top, start=1):
        if not rows or entry.xp != rows[-1]["profile"].xp:
            place = index
        me = entry.user_id == player.id
        # Анонимного игрока другие видят как «Аноним», а сам он — под своим именем.
        hidden = entry.leaderboard_anonymous and not me
        rows.append({"place": place, "profile": entry, "me": me, "hidden": hidden})
    mine = player.profile
    my_place = None
    if not mine.is_guest and mine.xp > 0:
        my_place = ranked.filter(xp__gt=mine.xp).count() + 1
    context = {"rows": rows, "my_place": my_place, "in_top": any(r["me"] for r in rows)}
    return render(request, "learning/leaderboard.html", context)


@login_required
@open_lesson_required
def lesson_start(request, lesson_id):
    get_player(request)
    lesson = get_object_or_404(Lesson, id=lesson_id)
    engine.start(request.session, lesson)
    return redirect("learning:lesson_play", lesson_id=lesson.id)


def _body_context(run, exercise, feedback=None, given=""):
    # Порядок вариантов фиксирован для пары (упражнение, позиция), чтобы не прыгал после ответа.
    rng = random.Random(f"{exercise.id}-{run['pos']}")
    options = list(exercise.options)
    if exercise.kind == Exercise.Kind.MATCH:
        left = [p[0] for p in options]
        right = [p[1] for p in options]
        rng.shuffle(left)
        rng.shuffle(right)
        options = {"left": left, "right": right, "pairs": dict(map(tuple, exercise.options))}
    else:
        rng.shuffle(options)
    return {
        "run": run,
        "exercise": exercise,
        "options": options,
        "progress": engine.progress_percent(run),
        "feedback": feedback,
        "given": given,
        "failed": engine.is_failed(run),
        "udmurt_keys": UDMURT_KEYS,
    }


@login_required
@open_lesson_required
def lesson_play(request, lesson_id):
    get_player(request)
    run = engine.get_run(request.session, lesson_id)
    if run is None:
        return redirect("learning:lesson_start", lesson_id=lesson_id)
    exercise = engine.current_exercise(run)
    if exercise is None:
        return redirect("learning:lesson_next", lesson_id=lesson_id)
    lesson = get_object_or_404(Lesson, id=lesson_id)
    ctx = _body_context(run, exercise) | {"lesson": lesson}
    return render(request, "learning/lesson.html", ctx)


@login_required
@require_POST
@open_lesson_required
def lesson_answer(request, lesson_id):
    run = engine.get_run(request.session, lesson_id)
    if run is None:
        return redirect("learning:lesson_start", lesson_id=lesson_id)
    exercise = engine.current_exercise(run)
    if exercise is None:
        return redirect("learning:lesson_play", lesson_id=lesson_id)
    given = request.POST.get("answer", "")
    if not given.strip():
        # Пустой ответ не проверяем и сердечко за него не снимаем — показываем задание снова.
        feedback = None
    else:
        try:
            match_mistakes = min(int(request.POST.get("mistakes", 0)), MAX_MATCH_MISTAKES)
        except ValueError:
            match_mistakes = 0
        feedback = engine.submit(request.session, run, exercise, given, match_mistakes)
    ctx = _body_context(run, exercise, feedback=feedback, given=given)
    ctx["lesson"] = exercise.lesson
    if not request.htmx:
        return render(request, "learning/lesson.html", ctx)
    return render(request, "learning/partials/lesson_body.html", ctx)


@login_required
@open_lesson_required
def lesson_next(request, lesson_id):
    player = get_player(request)
    run = engine.get_run(request.session, lesson_id)
    if run is None:
        return redirect("learning:lesson_start", lesson_id=lesson_id)
    if engine.is_failed(run):
        return redirect("learning:lesson_start", lesson_id=lesson_id)
    if run["answered"]:
        engine.advance(request.session, run)

    if engine.is_finished(run):
        engine.finish(request.session, player, run)
        url = reverse("learning:lesson_result", args=[lesson_id])
        if request.htmx:
            response = HttpResponse()
            response["HX-Redirect"] = url
            return response
        return redirect(url)

    if not request.htmx:
        return redirect("learning:lesson_play", lesson_id=lesson_id)
    exercise = engine.current_exercise(run)
    ctx = _body_context(run, exercise) | {"lesson": exercise.lesson}
    return render(request, "learning/partials/lesson_body.html", ctx)


@login_required
def lesson_result(request, lesson_id):
    get_player(request)
    result = request.session.get(engine.RESULT_KEY)
    if not result or result["lesson_id"] != lesson_id:
        return redirect("learning:home")
    lesson = get_object_or_404(Lesson, id=lesson_id)
    return render(request, "learning/result.html", {"lesson": lesson, "result": result})
