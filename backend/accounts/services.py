import uuid

from django.contrib.auth import get_user_model, login

from .models import Profile


def get_player(request):
    """Возвращает текущего игрока (игровые экраны закрыты login_required) и следит, чтобы у него
    был профиль — например, у суперпользователя, созданного через createsuperuser."""
    Profile.objects.get_or_create(user=request.user, defaults={"is_guest": False})
    return request.user


def create_guest(request):
    """Создаёт гостевой аккаунт и входит под ним: играть можно без регистрации,
    а регистрация потом превращает гостя в постоянного игрока."""
    user = get_user_model().objects.create_user(username=f"guest-{uuid.uuid4().hex[:10]}")
    Profile.objects.create(user=user, is_guest=True)
    login(request, user)
    return user
