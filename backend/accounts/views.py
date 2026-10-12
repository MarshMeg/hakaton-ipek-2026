from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render

from .forms import SignupForm
from .services import get_player


def signup(request):
    player = get_player(request)
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        player.username = form.cleaned_data["username"]
        player.set_password(form.cleaned_data["password"])
        player.save()
        player.profile.is_guest = False
        player.profile.save(update_fields=["is_guest"])
        # После смены пароля сессию нужно обновить, иначе игрока разлогинит.
        login(request, player)
        return redirect("learning:home")
    return render(request, "accounts/signup.html", {"form": form})


class PlayerLoginView(LoginView):
    template_name = "accounts/login.html"
