from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render

from courses.models import Lesson

from .forms import SignupForm
from .models import Profile
from .services import get_player


def signup(request):
    user = request.user
    if user.is_authenticated and not user.profile.is_guest:
        return redirect("learning:home")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        username, password = form.cleaned_data["username"], form.cleaned_data["password"]
        if user.is_authenticated:
            # Гостевые аккаунты остались от прежней версии (игра без регистрации): такой гость
            # становится постоянным игроком на месте — прогресс сохраняется.
            user.username = username
            user.set_password(password)
            user.save()
            user.profile.is_guest = False
            user.profile.save(update_fields=["is_guest"])
        else:
            user = get_user_model().objects.create_user(username=username, password=password)
            Profile.objects.create(user=user, is_guest=False)
        # После смены пароля сессию нужно обновить, иначе игрока разлогинит.
        login(request, user)
        return redirect("learning:home")
    return render(request, "accounts/signup.html", {"form": form})


@login_required
def profile(request):
    player = get_player(request)
    results = player.lesson_results.select_related("lesson")
    context = {
        "player": player,
        "lessons_done": results.values("lesson").distinct().count(),
        "lessons_total": Lesson.objects.count(),
        "recent_results": results[:5],
    }
    return render(request, "accounts/profile.html", context)


class PlayerLoginView(LoginView):
    """Первый экран игры: сюда попадает каждый, кто ещё не вошёл."""

    template_name = "accounts/login.html"
    redirect_authenticated_user = True
