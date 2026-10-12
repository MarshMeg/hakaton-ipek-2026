from django.contrib.auth import get_user_model, login
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .forms import SignupForm
from .models import Profile
from .services import create_guest


def signup(request):
    user = request.user
    if user.is_authenticated and not user.profile.is_guest:
        return redirect("learning:home")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        username, password = form.cleaned_data["username"], form.cleaned_data["password"]
        if user.is_authenticated:
            # Гость становится постоянным игроком на месте — прогресс сохраняется.
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


@require_POST
def guest_login(request):
    if not request.user.is_authenticated:
        create_guest(request)
    return redirect("learning:home")


class PlayerLoginView(LoginView):
    """Первый экран игры: сюда попадает каждый, кто ещё не вошёл."""

    template_name = "accounts/login.html"
    redirect_authenticated_user = True
