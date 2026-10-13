from .models import Profile


def get_player(request):
    """Возвращает текущего игрока (игровые экраны закрыты login_required) и следит, чтобы у него
    был профиль — например, у суперпользователя, созданного через createsuperuser."""
    Profile.objects.get_or_create(user=request.user, defaults={"is_guest": False})
    return request.user
