from django.contrib import admin

from .models import Course, Exercise, Lesson, Unit


class UnitInline(admin.TabularInline):
    model = Unit
    extra = 0


class LessonInline(admin.TabularInline):
    model = Lesson
    extra = 0


class ExerciseInline(admin.StackedInline):
    model = Exercise
    extra = 0
    fields = ("order", "kind", "prompt", "answer", "options", "hint", "audio", "image")


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "slug")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [UnitInline]


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("title", "title_udm", "course", "order")
    list_filter = ("course",)
    inlines = [LessonInline]


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("title", "unit", "order")
    list_filter = ("unit__course", "unit")
    inlines = [ExerciseInline]


@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = ("prompt", "kind", "lesson", "order")
    list_filter = ("kind", "lesson__unit")
    search_fields = ("prompt", "answer")
