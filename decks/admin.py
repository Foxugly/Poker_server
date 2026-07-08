from django.contrib import admin
from parler.admin import TranslatableAdmin, TranslatableTabularInline

from .models import Card, Deck, TextLayer, VoteType


@admin.register(VoteType)
class VoteTypeAdmin(TranslatableAdmin):
    list_display = ("code", "resolution_strategy", "is_active")


class TextLayerInline(TranslatableTabularInline):
    model = TextLayer
    extra = 0


@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ("slug", "value", "order", "deck", "is_active")
    list_filter = ("deck",)
    ordering = ("deck", "order")
    inlines = [TextLayerInline]


@admin.register(Deck)
class DeckAdmin(TranslatableAdmin):
    list_display = ("__str__", "vote_type", "is_standard", "is_active")
