"""Editable deck referential (data-model spec §3). Translations live as parler rows
keyed by language_code ("langue = donnée", scope §10) — never label_fr columns.

At room creation the referential is frozen into an immutable JSON ``deck_snapshot``
(spec §4); the realtime layer never reads these tables.
"""
from django.db import models
from parler.models import TranslatableModel, TranslatedFields


class TextLayerKind(models.TextChoices):
    STATIC = "static", "Static (one value, all languages)"
    I18N = "i18n", "Translated (per-language)"


class LayerAlign(models.TextChoices):
    LEFT = "left", "Left"
    CENTER = "center", "Center"
    RIGHT = "right", "Right"


class VoteType(TranslatableModel):
    """Abstract vote type (spec §3.1). Phase 1: a single ``delegation_poker`` row.
    ``resolution_strategy`` is an identifier routed in code (principle P1)."""

    code = models.SlugField(unique=True)
    resolution_strategy = models.CharField(max_length=64)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    translations = TranslatedFields(
        name=models.CharField(max_length=120),
    )

    def __str__(self):
        return self.code


class CardBack(TranslatableModel):
    """A card back, catalogued independently of the fronts.

    A team picks its fronts (``Deck``) and its back separately, so any back can be
    paired with any deck. ``Deck.card_back_image`` stays as the deck's own default,
    used when a team hasn't picked a back.
    """

    team = models.ForeignKey(
        "teams.Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="card_backs"
    )
    is_standard = models.BooleanField(default=True)
    # Included in the free offer. Distinct from is_standard, which says who OWNS a
    # back (nobody vs a team): a common back can still be reserved to paid teams.
    free_tier = models.BooleanField(default=True)
    image = models.ImageField(upload_to="decks/backs/")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    translations = TranslatedFields(
        name=models.CharField(max_length=120),
    )

    def __str__(self):
        for lang in ("en", "fr"):
            name = self.safe_translation_getter("name", language_code=lang, any_language=False)
            if name:
                return name
        return f"CardBack<{self.pk}>"


class Deck(TranslatableModel):
    """A set of cards for a vote type (spec §3.2). A deck is either *standard*
    (``team`` null, offered to every team) or a team's own custom deck."""

    vote_type = models.ForeignKey(VoteType, on_delete=models.PROTECT, related_name="decks")
    team = models.ForeignKey(
        "teams.Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="owned_decks"
    )
    is_standard = models.BooleanField(default=True)
    # Included in the free offer. Distinct from is_standard, which says who OWNS a
    # deck (nobody vs a team): a common deck can still be reserved to paid teams.
    free_tier = models.BooleanField(default=True)
    card_back_image = models.ImageField(upload_to="decks/backs/")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    translations = TranslatedFields(
        name=models.CharField(max_length=120),
    )

    def __str__(self):
        # Admin label: the English name, else the French one, else a technical
        # fallback — a deck with no translation at all must still be listable.
        for lang in ("en", "fr"):
            name = self.safe_translation_getter("name", language_code=lang, any_language=False)
            if name:
                return name
        return f"Deck<{self.pk}> ({self.vote_type_id})"


class Card(models.Model):
    """A card of a deck (spec §3.3). ``value`` is the language-agnostic canonical
    value referenced by Vote.card_value / Result.chosen_value (Delegation Poker: "1".."7")."""

    deck = models.ForeignKey(Deck, on_delete=models.CASCADE, related_name="cards")
    value = models.CharField(max_length=32)
    slug = models.SlugField()
    order = models.PositiveSmallIntegerField()
    background_image = models.ImageField(upload_to="decks/cards/")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("deck", "order")
        constraints = [
            models.UniqueConstraint(fields=("deck", "value"), name="uniq_card_deck_value"),
            models.UniqueConstraint(fields=("deck", "order"), name="uniq_card_deck_order"),
        ]

    def __str__(self):
        return f"{self.slug} ({self.value})"


class TextLayer(TranslatableModel):
    """N overlaid text layers per card (spec §3.4). Position/size in % (responsive);
    ``content`` is a translated field — a ``static`` layer stores only the fallback
    (EN) row and parler serves it everywhere; an ``i18n`` layer stores N rows."""

    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="layers")
    order = models.PositiveSmallIntegerField(default=1)
    pos_x = models.DecimalField(max_digits=5, decimal_places=2)  # % 0-100
    pos_y = models.DecimalField(max_digits=5, decimal_places=2)  # % 0-100
    font_family = models.CharField(max_length=80, default="Inter")
    font_size = models.DecimalField(max_digits=5, decimal_places=2)  # % of card height
    font_weight = models.PositiveSmallIntegerField(default=400)
    color = models.CharField(max_length=9, default="#ffffff")  # #RRGGBB[AA]
    align = models.CharField(max_length=6, choices=LayerAlign.choices, default=LayerAlign.CENTER)
    content_kind = models.CharField(max_length=6, choices=TextLayerKind.choices, default=TextLayerKind.I18N)

    translations = TranslatedFields(
        content=models.CharField(max_length=200),
    )

    class Meta:
        ordering = ("card", "order")

    def __str__(self):
        return f"Layer<{self.pk}> card={self.card_id} order={self.order}"
