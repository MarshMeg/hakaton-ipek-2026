import uuid
from io import BytesIO

from django import forms
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db.models.functions import Length
from PIL import Image, ImageOps

AVATAR_SIZE = 256  # аватарка хранится квадратом 256×256, что бы ни загрузили
AVATAR_MAX_BYTES = 5 * 1024 * 1024


def username_taken(username: str, exclude_pk=None) -> bool:
    """Занято ли имя без учёта регистра. Сравниваем в Python: на SQLite `iexact` и LOWER()
    понимают только латиницу, и «ДЕМО» не совпало бы с «демо».
    Из БД берём лишь имена той же длины."""
    candidates = get_user_model().objects.annotate(length=Length("username"))
    candidates = candidates.filter(length=len(username)).exclude(pk=exclude_pk)
    folded = username.casefold()
    return any(name.casefold() == folded for name in candidates.values_list("username", flat=True))


class SignupForm(forms.Form):
    """Регистрация игрока (и превращение старого гостевого аккаунта в постоянный)."""

    name = forms.CharField(label="Имя", max_length=150)
    family = forms.CharField(label="Фамилия", max_length=150)
    username = forms.CharField(label="Имя пользователя (для входа)", max_length=150)
    password = forms.CharField(label="Пароль", widget=forms.PasswordInput, min_length=6)

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if username_taken(username):
            raise forms.ValidationError("Такое имя уже занято")
        return username


class ProfileForm(forms.Form):
    """Редактирование своих данных: имя и фамилия (для показа), username (для входа), аватарка."""

    name = forms.CharField(label="Имя", max_length=150)
    family = forms.CharField(label="Фамилия", max_length=150)
    username = forms.CharField(label="Имя пользователя (для входа)", max_length=150)
    avatar = forms.ImageField(label="Аватарка", required=False)
    remove_avatar = forms.BooleanField(label="Убрать аватарку", required=False)

    def __init__(self, *args, user, **kwargs):
        self.user = user
        initial = {
            "name": user.first_name,
            "family": user.last_name,
            "username": user.username,
        }
        super().__init__(*args, initial=initial, **kwargs)

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if username_taken(username, exclude_pk=self.user.pk):
            raise forms.ValidationError("Такое имя уже занято")
        return username

    def clean_avatar(self):
        upload = self.cleaned_data.get("avatar")
        if not upload:
            return None
        if upload.size > AVATAR_MAX_BYTES:
            raise forms.ValidationError("Картинка слишком большая — не больше 5 МБ")
        # Приводим к одному виду: поворот по EXIF, квадрат по центру, JPEG.
        upload.seek(0)
        image = ImageOps.exif_transpose(Image.open(upload)).convert("RGB")
        image = ImageOps.fit(image, (AVATAR_SIZE, AVATAR_SIZE))
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        return ContentFile(buffer.getvalue(), name=f"{uuid.uuid4().hex}.jpg")

    def save(self):
        data, user, profile = self.cleaned_data, self.user, self.user.profile
        user.username = data["username"]
        user.first_name, user.last_name = data["name"].strip(), data["family"].strip()
        user.save(update_fields=["username", "first_name", "last_name"])
        if data["avatar"] or data["remove_avatar"]:
            if profile.avatar:
                profile.avatar.delete(save=False)
            if data["avatar"]:
                profile.avatar.save(data["avatar"].name, data["avatar"], save=False)
            profile.save(update_fields=["avatar"])
        return user
