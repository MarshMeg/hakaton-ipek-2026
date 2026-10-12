def player(request):
    """Пробрасывает профиль игрока во все шаблоны (XP и стрик в шапке)."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"profile": None}
    return {"profile": getattr(user, "profile", None)}
