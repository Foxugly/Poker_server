"""Create the standard Delegation Poker deck (7 cards, 2 layers each).

Used by tests and by the ``seed_delegation_deck`` management command. Image fields are
set to placeholder names by default — the original illustrations are a non-technical
content dependency (scope §10); the code is ready before the artwork exists.
"""
from decks.models import Card, Deck, TextLayer, TextLayerKind, VoteType

LEVELS = [
    ("1", "tell", "Tell", "Dire", "Vertellen", "Dire", "Decir"),
    ("2", "sell", "Sell", "Vendre", "Verkopen", "Vendere", "Vender"),
    ("3", "consult", "Consult", "Consulter", "Raadplegen", "Consultare", "Consultar"),
    ("4", "agree", "Agree", "S'accorder", "Afspreken", "Concordare", "Acordar"),
    ("5", "advise", "Advise", "Conseiller", "Adviseren", "Consigliare", "Aconsejar"),
    ("6", "inquire", "Inquire", "S'enquérir", "Informeren", "Informarsi", "Indagar"),
    ("7", "delegate", "Delegate", "Déléguer", "Delegeren", "Delegare", "Delegar"),
]
LANG_ORDER = ("en", "fr", "nl", "it", "es")


def create_standard_deck():
    vt, _ = VoteType.objects.get_or_create(
        code="delegation_poker", defaults={"resolution_strategy": "delegation_v1"}
    )
    vt.set_current_language("en")
    vt.name = "Delegation Poker"
    vt.save()

    deck = Deck.objects.create(
        vote_type=vt, is_standard=True, card_back_image="decks/backs/back.webp"
    )
    deck.set_current_language("en")
    deck.name = "Delegation Poker"
    deck.save()

    for value, slug, *names in LEVELS:
        card = Card.objects.create(
            deck=deck, value=value, slug=slug, order=int(value),
            background_image=f"decks/cards/{slug}.webp",
        )
        num = TextLayer.objects.create(
            card=card, order=1, pos_x=12, pos_y=12, font_size=9, font_weight=700,
            content_kind=TextLayerKind.STATIC,
        )
        num.set_current_language("en")
        num.content = value
        num.save()

        name_layer = TextLayer.objects.create(
            card=card, order=2, pos_x=50, pos_y=82, font_size=7, font_weight=600,
            content_kind=TextLayerKind.I18N,
        )
        for lang, text in zip(LANG_ORDER, names):
            name_layer.set_current_language(lang)
            name_layer.content = text
            name_layer.save()
    return deck


SHARED_CARD_FRONT = "decks/cards/front_cartes_foxugly.png"
# Repli seulement : ``_standard_card_back()`` prend d'abord un dos reellement
# present au catalogue. Ce nom-la est un placeholder herite du premier deck, et
# le fichier n'existe pas — une salle sans compte affichait donc un rectangle nu.
FALLBACK_CARD_BACK = "decks/backs/back.webp"


def _standard_card_back():
    """Le dos par defaut d'un nouveau deck : le premier dos maison du catalogue.

    Le resoudre au lieu de coder un nom en dur evite de reproduire le placeholder
    d'origine, dont le fichier n'a jamais ete televerse. Ce dos ne sert qu'aux
    salles sans compte : une equipe qui a choisi le sien passe avant (selection.py).
    """
    from .models import CardBack

    back = CardBack.objects.filter(is_standard=True, is_active=True).order_by("pk").first()
    return back.image.name if back and back.image else FALLBACK_CARD_BACK

# Le fond partage est un eclat pastel tres CLAIR au centre (quasi blanc), borde de
# noir. Un pictogramme blanc y serait invisible — d'ou un quasi-noir, qui reprend la
# bordure de la carte. A revoir si le fond change pour une illustration sombre.
ICON_COLOR = "#111111"

ICON_DIR = "decks/icons"

# (valeur, slug, ordre, fichier du pictogramme)
FIST_OF_FIVE_CARDS = [
    ("0", "fist-0", 0, f"{ICON_DIR}/fist-0.png"),
    ("1", "fist-1", 1, f"{ICON_DIR}/fist-1.png"),
    ("2", "fist-2", 2, f"{ICON_DIR}/fist-2.png"),
    ("3", "fist-3", 3, f"{ICON_DIR}/fist-3.png"),
    ("4", "fist-4", 4, f"{ICON_DIR}/fist-4.png"),
    ("5", "fist-5", 5, f"{ICON_DIR}/fist-5.png"),
]
ROMAN_VOTE_CARDS = [
    ("+1", "thumb-up", 1, f"{ICON_DIR}/thumb-up.png"),
    # Le neutre est un poing ferme — ni pour, ni contre — et non un pouce a
    # l'horizontale, d'ou « neutral » plutot que « side ».
    ("0", "thumb-neutral", 2, f"{ICON_DIR}/thumb-neutral.png"),
    ("-1", "thumb-down", 3, f"{ICON_DIR}/thumb-down.png"),
]


def _create_icon_deck(vote_type_code, resolution_strategy, names, cards):
    """Un deck muet : chaque carte porte une unique couche ``icon`` plein cadre.

    ``names`` est un dict {code_langue: nom du deck}. Les cartes n'ont aucune couche
    ``i18n`` : la valeur brute est ce qui s'affiche dans les surfaces de resultat, et
    elle a ete choisie pour se lire dans les cinq langues.
    """
    vt, _ = VoteType.objects.get_or_create(
        code=vote_type_code, defaults={"resolution_strategy": resolution_strategy}
    )
    vt.set_current_language("en")
    vt.name = names["en"]
    vt.save()

    deck = Deck.objects.create(
        vote_type=vt, is_standard=True, free_tier=False, card_back_image=_standard_card_back()
    )
    for lang, name in names.items():
        deck.set_current_language(lang)
        deck.name = name
        deck.save()

    for value, slug, order, icon_image in cards:
        card = Card.objects.create(
            deck=deck, value=value, slug=slug, order=order,
            background_image=SHARED_CARD_FRONT,
        )
        # Aucun texte : une couche icon dessine son image. Le pictogramme est une
        # donnee comme les autres visuels — en ajouter un est un televersement,
        # jamais une livraison du frontend.
        TextLayer.objects.create(
            card=card, order=1, pos_x=50, pos_y=50, font_size=55,
            color=ICON_COLOR, content_kind=TextLayerKind.ICON, image=icon_image,
        )
    return deck


def create_fist_of_five_deck():
    """Gradation d'adhesion de 0 a 5, SANS regle de veto : le 0 signifie
    « je n'adhere pas du tout », pas « je bloque »."""
    return _create_icon_deck(
        "fist_of_five",
        "fist_of_five_v1",
        # Nom de methode, garde tel quel dans les cinq langues (modifiable en admin).
        {lang: "Fist of Five" for lang in LANG_ORDER},
        FIST_OF_FIVE_CARDS,
    )


def create_roman_vote_deck():
    """Pour / neutre / contre. Les valeurs +1, 0 et -1 se lisent dans les cinq langues,
    ce qui evite toute traduction : elles ressortent brutes dans les surfaces de resultat."""
    return _create_icon_deck(
        "roman_vote",
        "roman_v1",
        {
            "en": "Roman Vote",
            "fr": "Vote romain",
            "nl": "Romeinse stemming",
            "it": "Voto romano",
            "es": "Voto romano",
        },
        ROMAN_VOTE_CARDS,
    )
