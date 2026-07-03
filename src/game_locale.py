"""In-game UI strings for Mini War — banner, tabs, stock labels, item aliases.

Catalog / wishlist names stay English internally; localized aliases map OCR text
back to those canonical names. Use game.locale = \"auto\" (default) to accept all
supported languages at once.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

# Canonical English rarities (catalog + reports).
RARITIES = (
    "Common", "Uncommon", "Rare", "Epic",
    "Legendary", "Mythic", "Secret", "Divine",
)


def fold_accents(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _norm_text(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", fold_accents(s).lower())


# --- per-locale packs (normalized fragments unless noted) -------------------

def _pack(
    *,
    banner_confirm: list[str],
    shop_tabs: list[str],
    shop_markers: list[str],
    vendor_talk: list[str],
    stoplist: list[str],
    bad_name_substr: list[str],
    stock_out: list[str],
    locked: list[str],
    stock_keywords: list[str],
    rarities: list[tuple[str, str]],
    items: dict[str, list[str]] | None = None,
) -> dict:
    return {
        "banner_confirm": banner_confirm,
        "shop_tabs": shop_tabs,
        "shop_markers": shop_markers,
        "vendor_talk": vendor_talk,
        "stoplist": stoplist,
        "bad_name_substr": bad_name_substr,
        "stock_out": stock_out,
        "locked": locked,
        "stock_keywords": stock_keywords,
        "rarities": rarities,
        "items": items or {},
    }


_EN = _pack(
    banner_confirm=[
        "restocke", "beenrestock", "shophasbeenrestock", "shophasbeen",
        "hasbeenrestock", "beenrestocked",
    ],
    shop_tabs=["factory", "houses", "house", "military", "special"],
    shop_markers=[
        "common", "uncommon", "rare", "epic", "legendary", "mythic",
        "secret", "divine", "out of stock", "stock x", "stockx",
    ],
    vendor_talk=["talk", "parlez", "parler", "hablar", "sprechen", "falar"],
    stoplist=[
        "factory", "houses", "house", "military", "special", "shop", "restock",
        "buy", "sell", "country", "talk", "premium", "stock", "owned", "max",
        "min", "sec", "x", "acheter", "vendre", "pays", "boutique", "marchand",
        "usine", "maisons", "militaire", "fabrik", "militar", "comprar", "vender",
    ],
    bad_name_substr=[
        "outofstock", "stockx", "instock", "researching", "locked", "unlock",
        "epuise", "agotado", "esaurito", "ausverkauft",
    ],
    stock_out=[
        "outofstock", "outoftock", "outofstoc", "outofst", "epuise", "agotado",
        "esaurito", "ausverkauft", "rupture", "sinexistencias",
    ],
    locked=["researching", "locked", "unlock", "verrouille", "bloqueado", "gesperrt"],
    stock_keywords=["stock", "voorraad", "estoque", "inventario"],
    rarities=[
        ("common", "Common"), ("uncommon", "Uncommon"), ("rare", "Rare"),
        ("epic", "Epic"), ("legendary", "Legendary"), ("mythic", "Mythic"),
        ("secret", "Secret"), ("divine", "Divine"),
    ],
)

_FR = _pack(
    banner_confirm=[
        "reapprovisionne", "reapprovisionnee", "magasinabete", "magasinreappro",
        "boutiquereappro", "beenrestock", "restocke",
    ],
    shop_tabs=["usine", "maisons", "maison", "militaire", "special", "speciale"],
    shop_markers=[
        "commun", "peucommun", "rare", "epique", "legendaire", "mythique",
        "secret", "divin", "epuise", "stock x", "stockx", "enstock",
    ],
    vendor_talk=["parlez", "parler", "talk"],
    stoplist=list(_EN["stoplist"]) + [
        "commun", "legendaire", "mythique", "divin", "epuise", "enstock",
    ],
    bad_name_substr=list(_EN["bad_name_substr"]) + ["recherche", "verrouille"],
    stock_out=["epuise", "rupture", "plusdestock", "outofstock"],
    locked=["recherche", "verrouille", "verouille", "bloque"],
    stock_keywords=["stock"],
    rarities=[
        ("commun", "Common"), ("peucommun", "Uncommon"), ("rare", "Rare"),
        ("epique", "Epic"), ("legendaire", "Legendary"), ("mythique", "Mythic"),
        ("secret", "Secret"), ("divin", "Divine"),
    ],
    items={
        "Gold Cave": ["Caverne d'or", "Caverne dor"],
        "Bank": ["Banque"],
        "Research Labs": ["Laboratoires de recherche", "Labos de recherche"],
        "Diamond Cave": ["Caverne de diamant"],
        "Uranium Cave": ["Caverne d'uranium"],
        "Nuclear Reactor": ["Réacteur nucléaire", "Reacteur nucleaire"],
        "Data Center": ["Centre de données", "Centre de donnees"],
        "Blackhole Generator": ["Générateur de trou noir", "Generateur de trou noir"],
        "Antimatter Reactor": ["Réacteur à antimatière", "Reacteur antimatiere"],
        "Area 51 Lab": ["Labo Area 51", "Laboratoire Area 51"],
        "Quantum Core Generator": ["Générateur de noyau quantique", "Generateur noyau quantique"],
        "Supernova Accelerator": ["Accélérateur de supernova", "Accelerateur supernova"],
        "Helix Tower": ["Tour Hélice", "Tour Helice"],
        "The Manor": ["Le Manoir", "Manoir"],
        "Hotel": ["Hôtel", "Hotel"],
        "Giant Skyscraper": ["Gratte-ciel géant", "Gratte-ciel geant"],
        "Double Turbo Tower": ["Double tour turbo"],
        "Grand Hotel": ["Grand hôtel", "Grand hotel"],
        "Missile Launcher": ["Lance-missiles", "Lance missiles"],
        "Military Hospital": ["Hôpital militaire", "Hopital militaire"],
        "General's Base": ["Base du général", "Base du general"],
        "Air Base": ["Base aérienne", "Base aerienne"],
        "Artillery Depot": ["Dépôt d'artillerie", "Depot artillerie"],
        "Rocket Bunker": ["Bunker de roquettes"],
        "Mech Station": ["Station de mechs"],
        "Spider Base": ["Base d'araignées", "Base araignees"],
        "Air Fortress": ["Forteresse aérienne", "Forteresse aerienne"],
    },
)

_DE = _pack(
    banner_confirm=[
        "wiederaufgefullt", "aufgfullt", "ladenwurde", "shopwurde", "restocke",
        "reapprovisionne",
    ],
    shop_tabs=["fabrik", "hauser", "haus", "militar", "militarisch", "spezial"],
    shop_markers=[
        "gewohnlich", "ungewohnlich", "selten", "episch", "legendar", "mythisch",
        "geheim", "gottlich", "ausverkauft", "stock x", "stockx",
    ],
    vendor_talk=["sprechen", "reden", "talk", "parlez"],
    stoplist=list(_EN["stoplist"]) + ["fabrik", "hauser", "militar", "gewohnlich"],
    bad_name_substr=list(_EN["bad_name_substr"]) + ["forschung", "gesperrt"],
    stock_out=["ausverkauft", "nichtvorratig", "outofstock"],
    locked=["forschung", "gesperrt", "verriegelt"],
    stock_keywords=["stock", "bestand"],
    rarities=[
        ("gewohnlich", "Common"), ("ungewohnlich", "Uncommon"), ("selten", "Rare"),
        ("episch", "Epic"), ("legendar", "Legendary"), ("mythisch", "Mythic"),
        ("geheim", "Secret"), ("gottlich", "Divine"),
    ],
    items={
        "Air Fortress": ["Luftfestung", "Air Fortress"],
        "Quantum Core Generator": ["Quantenkern-Generator", "Quantenkern Generator"],
        "Supernova Accelerator": ["Supernova-Beschleuniger"],
    },
)

_ES = _pack(
    banner_confirm=[
        "reabastecida", "reabastecido", "tiendahasid", "restocke", "reapprovisionne",
    ],
    shop_tabs=["fabrica", "casas", "casa", "militar", "especial"],
    shop_markers=[
        "comun", "pococomun", "raro", "epico", "legendario", "mitico",
        "secreto", "divino", "agotado", "stock x", "stockx",
    ],
    vendor_talk=["hablar", "habla", "talk", "parlez"],
    stoplist=list(_EN["stoplist"]) + ["fabrica", "casas", "militar", "comprar"],
    bad_name_substr=list(_EN["bad_name_substr"]) + ["investigando", "bloqueado"],
    stock_out=["agotado", "sinexistencias", "outofstock"],
    locked=["investigando", "bloqueado", "desbloquear"],
    stock_keywords=["stock", "existencias"],
    rarities=[
        ("comun", "Common"), ("pococomun", "Uncommon"), ("raro", "Rare"),
        ("epico", "Epic"), ("legendario", "Legendary"), ("mitico", "Mythic"),
        ("secreto", "Secret"), ("divino", "Divine"),
    ],
    items={
        "Air Fortress": ["Fortaleza aérea", "Fortaleza aerea"],
        "Quantum Core Generator": ["Generador de núcleo cuántico"],
        "Supernova Accelerator": ["Acelerador de supernova"],
    },
)

_PT = _pack(
    banner_confirm=[
        "reabastecida", "reabastecido", "lojafoi", "restocke",
    ],
    shop_tabs=["fabrica", "casas", "casa", "militar", "especial"],
    shop_markers=[
        "comum", "incomum", "raro", "epico", "lendario", "mitico",
        "secreto", "divino", "esgotado", "stock x", "stockx",
    ],
    vendor_talk=["falar", "conversar", "talk", "parlez"],
    stoplist=list(_EN["stoplist"]) + ["fabrica", "casas", "militar"],
    bad_name_substr=list(_EN["bad_name_substr"]) + ["pesquisando", "bloqueado"],
    stock_out=["esgotado", "semestoque", "outofstock"],
    locked=["pesquisando", "bloqueado"],
    stock_keywords=["stock", "estoque"],
    rarities=[
        ("comum", "Common"), ("incomum", "Uncommon"), ("raro", "Rare"),
        ("epico", "Epic"), ("lendario", "Legendary"), ("mitico", "Mythic"),
        ("secreto", "Secret"), ("divino", "Divine"),
    ],
    items={
        "Air Fortress": ["Fortaleza aérea", "Fortaleza aerea"],
    },
)

_LOCALES: dict[str, dict] = {
    "en": _EN,
    "fr": _FR,
    "de": _DE,
    "es": _ES,
    "pt": _PT,
}

SUPPORTED_LOCALES = ("auto", "en", "fr", "de", "es", "pt")


@dataclass(frozen=True)
class GameUi:
    locale: str
    banner_confirm: tuple[str, ...]
    shop_tabs: tuple[str, ...]
    shop_markers: tuple[str, ...]
    vendor_talk: tuple[str, ...]
    stoplist: frozenset[str]
    bad_name_substr: tuple[str, ...]
    stock_out: tuple[str, ...]
    locked: tuple[str, ...]
    stock_keywords: tuple[str, ...]
    rarity_map: dict[str, str]
    item_aliases: dict[str, tuple[str, ...]]
    ocr_lang_type: str
    banner_lang_agnostic: bool


def _merge_lists(*packs: dict, key: str) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for p in packs:
        for v in p.get(key, []):
            if key == "banner_confirm":
                n = _norm_text(v.replace(" ", ""))
                token = v
            else:
                n = _norm_text(v)
                token = n
            if n not in seen:
                seen.add(n)
                out.append(token)
    return tuple(out)


def _merge_auto() -> dict:
    packs = list(_LOCALES.values())
    merged = _pack(
        banner_confirm=list(_merge_lists(*packs, key="banner_confirm")),
        shop_tabs=list(_merge_lists(*packs, key="shop_tabs")),
        shop_markers=list(_merge_lists(*packs, key="shop_markers")),
        vendor_talk=list(_merge_lists(*packs, key="vendor_talk")),
        stoplist=list(_merge_lists(*packs, key="stoplist")),
        bad_name_substr=list(_merge_lists(*packs, key="bad_name_substr")),
        stock_out=list(_merge_lists(*packs, key="stock_out")),
        locked=list(_merge_lists(*packs, key="locked")),
        stock_keywords=list(_merge_lists(*packs, key="stock_keywords")),
        rarities=[],
    )
    rarity_map: dict[str, str] = {}
    for p in packs:
        for frag, canon in p["rarities"]:
            rarity_map[_norm_text(frag)] = canon
    merged["rarities"] = list(rarity_map.items())
    items: dict[str, list[str]] = {}
    for p in packs:
        for canon, aliases in p.get("items", {}).items():
            items.setdefault(canon, [])
            for a in aliases:
                if a not in items[canon]:
                    items[canon].append(a)
    merged["items"] = items
    return merged


_AUTO = _merge_auto()


def locale_from_cfg(cfg: dict | None) -> str:
    if not cfg:
        return "auto"
    loc = (cfg.get("game") or {}).get("locale")
    if not loc:
        loc = (cfg.get("ocr") or {}).get("game_locale")  # legacy alt key
    loc = str(loc or "auto").strip().lower()
    return loc if loc in SUPPORTED_LOCALES else "auto"


def ocr_lang_for_cfg(cfg: dict | None) -> str:
    if cfg:
        raw = (cfg.get("ocr") or {}).get("lang_type", "")
        if raw and str(raw).strip().lower() not in ("", "auto"):
            return str(raw).strip().lower()
    loc = locale_from_cfg(cfg)
    if loc == "en":
        return "en"
    return "latin"


@lru_cache(maxsize=8)
def build_ui(locale: str) -> GameUi:
    loc = locale if locale in _LOCALES else "auto"
    pack = _AUTO if loc == "auto" else _LOCALES[loc]
    rarity_map = {_norm_text(k): v for k, v in pack["rarities"]}
    if loc == "auto":
        rarity_map = {_norm_text(k): v for k, v in _AUTO["rarities"]}
    items = {
        canon: tuple(aliases)
        for canon, aliases in pack.get("items", {}).items()
    }
    ocr = "latin" if loc == "auto" else ocr_lang_for_cfg({"game": {"locale": loc}, "ocr": {}})
    return GameUi(
        locale=loc,
        banner_confirm=tuple(pack["banner_confirm"]),
        shop_tabs=tuple(_norm_text(t) for t in pack["shop_tabs"]),
        shop_markers=tuple(_norm_text(m) for m in pack["shop_markers"]),
        vendor_talk=tuple(_norm_text(v) for v in pack["vendor_talk"]),
        stoplist=frozenset(_norm_text(s) for s in pack["stoplist"]),
        bad_name_substr=tuple(_norm_text(b) for b in pack["bad_name_substr"]),
        stock_out=tuple(_norm_text(s) for s in pack["stock_out"]),
        locked=tuple(_norm_text(s) for s in pack["locked"]),
        stock_keywords=tuple(pack["stock_keywords"]),
        rarity_map=rarity_map,
        item_aliases=items,
        ocr_lang_type=ocr,
        banner_lang_agnostic=False,
    )


def get_ui(cfg: dict | None = None) -> GameUi:
    return build_ui(locale_from_cfg(cfg))


def confirm_banner_text(text: str, ui: GameUi) -> bool:
    """True only when OCR reads a known restock-banner phrase (not generic green UI)."""
    norm = _norm_text(text.replace(" ", ""))
    return any(p in norm for p in (_norm_text(p) for p in ui.banner_confirm))


def shop_text_hits(text: str, ui: GameUi) -> tuple[int, bool]:
    """Return (tab_hits, has_shop_marker) on normalized OCR text."""
    norm = _norm_text(text)
    tab_hits = sum(1 for t in ui.shop_tabs if t in norm)
    has_marker = any(m in norm for m in ui.shop_markers)
    return tab_hits, has_marker


def is_vendor_talk(text: str, ui: GameUi) -> bool:
    norm = _norm_text(text.replace(" ", ""))
    return any(v in norm for v in ui.vendor_talk)
