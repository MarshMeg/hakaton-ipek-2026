from django.contrib import admin

from .models import Fact, SortingSet, Topic, Word


class WordInline(admin.TabularInline):
    model = Word
    extra = 0
    fields = (
        "order",
        "udm",
        "ru",
        "alt",
        "transcription",
        "emoji",
        "image",
        "audio",
        "needs_check",
    )


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ("title", "title_udm", "kind", "family", "order")
    list_editable = ("order",)
    prepopulated_fields = {"slug": ("title",)}
    inlines = [WordInline]


@admin.register(Word)
class WordAdmin(admin.ModelAdmin):
    list_display = ("udm", "ru", "topic", "transcription", "needs_check")
    list_filter = ("topic",)
    search_fields = ("udm", "ru", "alt")


admin.site.register(SortingSet)
admin.site.register(Fact)
