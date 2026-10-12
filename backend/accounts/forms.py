from django import forms
from django.contrib.auth import get_user_model


class SignupForm(forms.Form):
    """Регистрация игрока (и превращение старого гостевого аккаунта в постоянный)."""

    username = forms.CharField(label="Имя пользователя", max_length=150)
    password = forms.CharField(label="Пароль", widget=forms.PasswordInput, min_length=6)

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if get_user_model().objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Такое имя уже занято")
        return username
