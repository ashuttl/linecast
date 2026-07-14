"""Localized UI strings for the maps view."""

_STRINGS = {
    "en": {"hint": "+/- zoom · drag pan · q quit",
           "unavailable": "terrain unavailable ({err})"},
    "fr": {"hint": "+/- zoom · glisser pour déplacer · q quitter",
           "unavailable": "relief indisponible ({err})"},
    "es": {"hint": "+/- zoom · arrastrar para mover · q salir",
           "unavailable": "terreno no disponible ({err})"},
    "de": {"hint": "+/- Zoom · Ziehen verschiebt · q beenden",
           "unavailable": "Gelände nicht verfügbar ({err})"},
    "it": {"hint": "+/- zoom · trascina per spostare · q esci",
           "unavailable": "terreno non disponibile ({err})"},
    "pt": {"hint": "+/- zoom · arrastar para mover · q sair",
           "unavailable": "terreno indisponível ({err})"},
    "nl": {"hint": "+/- zoom · slepen om te verschuiven · q stoppen",
           "unavailable": "terrein niet beschikbaar ({err})"},
    "pl": {"hint": "+/- zoom · przeciągnij aby przesunąć · q wyjście",
           "unavailable": "teren niedostępny ({err})"},
    "no": {"hint": "+/- zoom · dra for å flytte · q avslutt",
           "unavailable": "terreng utilgjengelig ({err})"},
    "sv": {"hint": "+/- zoom · dra för att flytta · q avsluta",
           "unavailable": "terräng otillgänglig ({err})"},
    "da": {"hint": "+/- zoom · træk for at flytte · q afslut",
           "unavailable": "terræn utilgængelig ({err})"},
    "is": {"hint": "+/- aðdráttur · draga til að færa · q hætta",
           "unavailable": "landslag ótiltækt ({err})"},
    "fi": {"hint": "+/- zoomaus · vedä siirtääksesi · q lopeta",
           "unavailable": "maasto ei saatavilla ({err})"},
    "ja": {"hint": "+/- ズーム · ドラッグで移動 · q 終了",
           "unavailable": "地形データ利用不可 ({err})"},
    "ko": {"hint": "+/- 줌 · 드래그로 이동 · q 종료",
           "unavailable": "지형 사용 불가 ({err})"},
    "zh": {"hint": "+/- 缩放 · 拖动平移 · q 退出",
           "unavailable": "地形不可用 ({err})"},
    "id": {"hint": "+/- zoom · seret untuk geser · q keluar",
           "unavailable": "medan tidak tersedia ({err})"},
}


def ms(key, lang, **kwargs):
    """Maps UI string for `lang`, falling back to English."""
    table = _STRINGS.get(lang, _STRINGS["en"])
    template = table.get(key, _STRINGS["en"].get(key, key))
    return template.format(**kwargs) if kwargs else template
