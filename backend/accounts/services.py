import uuid

from django.contrib.auth import get_user_model, login

from .models import Profile


def get_player(request):
    """Возвращает текущего игрока. Неавторизованному посетителю тихо создаётся гостевой аккаунт,
    чтобы ребёнок мог начать играть сразу, без регистрации."""
    if request.user.is_authenticated:
        Profile.objects.get_or_create(user=request.user, defaults={"is_guest": False})
        return request.user
    user = get_user_model().objects.create_user(username=f"guest-{uuid.uuid4().hex[:10]}")
    Profile.objects.create(user=user, is_guest=True)
    login(request, user)
    return user
