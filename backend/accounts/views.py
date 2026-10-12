from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.shortcuts import redirect, render
from django.urls import reverse_lazy

from courses.models import Lesson

from .forms import ProfileForm, SignupForm
from .models import Profile
from .services import get_player


def signup(request):
    user = request.user
    if user.is_authenticated and not user.profile.is_guest:
        return redirect("learning:home")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        username, password = data["username"], data["password"]
        names = {"first_name": data["name"].strip(), "last_name": data["family"].strip()}
        if user.is_authenticated:
            # Гостевые аккаунты остались от прежней версии (игра без регистрации): такой гость
            # становится постоянным игроком на месте — прогресс сохраняется.
            user.username = username
            user.first_name, user.last_name = names["first_name"], names["last_name"]
            user.set_password(password)
            user.save()
            user.profile.is_guest = False
            user.profile.save(update_fields=["is_guest"])
        else:
            user = get_user_model().objects.create_user(
                username=username, password=password, **names
            )
            Profile.objects.create(user=user, is_guest=False)
        # После смены пароля сессию нужно обновить, иначе игрока разлогинит.
        login(request, user)
        return redirect("learning:welcome")
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


@login_required
def profile_edit(request):
    player = get_player(request)
    form = ProfileForm(request.POST or None, request.FILES or None, user=player)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("accounts:profile")
    return render(request, "accounts/profile_edit.html", {"form": form})


class PlayerPasswordChangeView(PasswordChangeView):
    """Смена пароля из профиля: старый пароль и новый дважды; игрок остаётся в игре."""

    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:profile")


class PlayerLoginView(LoginView):
    """Первый экран игры: сюда попадает каждый, кто ещё не вошёл."""

    template_name = "accounts/login.html"
    redirect_authenticated_user = True
