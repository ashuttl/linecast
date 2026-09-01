"""The Hawaiian calendar against the published Kaulana Mahina.

The ground truth is the WPRFMC's printed table: every month of the
2025 and 2026 Hawaiʻi editions (their pages run Nov 2024 - Feb 2027),
each row a published Hilo..Muku span. The engine derives Hilo from
crescent visibility at Honolulu, so these are end-to-end checks that
the ephemeris and the Yallop cutoff land every month where the
printed calendar does — including the months visibility pushes Hilo
a second day past the conjunction, and the 29-night months that drop
Mauli.
"""

from datetime import date, timedelta

import pytest

from linecast._moon_i18n import _ANAHULU, _PO_MAHINA, anahulu_name, po_mahina_name
from linecast._pacific import (
    ANAHULU_COUNSEL,
    _NIGHT_NOTES,
    hawaiian_night,
    night_note,
)

# (Hilo, Muku) of every month in the 2025 and 2026 printed editions.
PUBLISHED_MONTHS = [
    (date(2024, 11, 2), date(2024, 12, 1)),
    (date(2024, 12, 2), date(2024, 12, 30)),
    (date(2024, 12, 31), date(2025, 1, 29)),
    (date(2025, 1, 30), date(2025, 2, 27)),
    (date(2025, 2, 28), date(2025, 3, 29)),
    (date(2025, 3, 30), date(2025, 4, 27)),
    (date(2025, 4, 28), date(2025, 5, 26)),
    (date(2025, 5, 27), date(2025, 6, 25)),
    (date(2025, 6, 26), date(2025, 7, 24)),
    (date(2025, 7, 25), date(2025, 8, 23)),
    (date(2025, 8, 24), date(2025, 9, 21)),
    (date(2025, 9, 22), date(2025, 10, 21)),
    (date(2025, 10, 22), date(2025, 11, 20)),
    (date(2025, 11, 21), date(2025, 12, 19)),
    (date(2025, 12, 20), date(2026, 1, 18)),
    (date(2026, 1, 19), date(2026, 2, 17)),
    (date(2026, 2, 18), date(2026, 3, 18)),
    (date(2026, 3, 19), date(2026, 4, 17)),
    (date(2026, 4, 18), date(2026, 5, 16)),
    (date(2026, 5, 17), date(2026, 6, 14)),
    (date(2026, 6, 15), date(2026, 7, 13)),
    (date(2026, 7, 14), date(2026, 8, 12)),
    (date(2026, 8, 13), date(2026, 9, 11)),
    (date(2026, 9, 12), date(2026, 10, 10)),
    (date(2026, 10, 11), date(2026, 11, 9)),
    (date(2026, 11, 10), date(2026, 12, 9)),
    (date(2026, 12, 10), date(2027, 1, 7)),
    (date(2027, 1, 8), date(2027, 2, 6)),
]


class TestPublishedMonths:
    @pytest.mark.parametrize("hilo,muku", PUBLISHED_MONTHS,
                             ids=lambda d: d.isoformat())
    def test_month_matches_the_printed_table(self, hilo, muku):
        nights = (muku - hilo).days + 1
        assert nights in (29, 30)
        assert hawaiian_night(hilo) == (1, nights)
        assert hawaiian_night(muku) == (nights, nights)

    def test_consecutive_days_stay_consecutive(self):
        prev = hawaiian_night(date(2025, 1, 1))
        for offset in range(1, 400):
            cur = hawaiian_night(date(2025, 1, 1) + timedelta(days=offset))
            if cur[0] == 1:
                assert prev[0] == prev[1]
            else:
                assert cur[0] == prev[0] + 1
                assert cur[1] == prev[1]
            prev = cur


class TestNightNames:
    def test_the_thirty_night_month_keeps_mauli(self):
        # Nana, Feb 28 - Mar 29 2025, as printed: thirty nights.
        assert po_mahina_name(*hawaiian_night(date(2025, 3, 28))) == "Mauli"
        assert po_mahina_name(*hawaiian_night(date(2025, 3, 29))) == "Muku"

    def test_the_29_night_month_drops_mauli(self):
        # Kaulua, Jan 30 - Feb 27 2025, as printed: Lono then Muku.
        assert po_mahina_name(*hawaiian_night(date(2025, 2, 26))) == "Lono"
        assert po_mahina_name(*hawaiian_night(date(2025, 2, 27))) == "Muku"

    def test_nights_from_the_printed_2026_pages(self):
        # Hinaiaʻeleʻele, Jun 15 - Jul 13 2026, spot checks per the page.
        cases = {
            date(2026, 6, 15): "Hilo",
            date(2026, 6, 24): "ʻOlepau",
            date(2026, 6, 29): "Hoku",
            date(2026, 7, 4): "Lāʻaupau",
            date(2026, 7, 8): "Kāloakūkahi",
            date(2026, 7, 13): "Muku",
        }
        for day, name in cases.items():
            assert po_mahina_name(*hawaiian_night(day)) == name

    def test_full_sequence_of_a_thirty_night_month(self):
        # Nana 2025 as printed, both ʻOle runs and all three Kū names.
        printed = [
            "Hilo", "Hoaka", "Kūkahi", "Kūlua", "Kūkolu",
            "Kūpau", "ʻOlekūkahi", "ʻOlekūlua", "ʻOlekūkolu", "ʻOlepau",
            "Huna", "Mōhalu", "Hua", "Akua", "Hoku",
            "Māhealani", "Kulu", "Lāʻaukūkahi", "Lāʻaukūlua", "Lāʻaupau",
            "ʻOlekūkahi", "ʻOlekūlua", "ʻOlepau", "Kāloakūkahi",
            "Kāloakūlua", "Kāloapau", "Kāne", "Lono", "Mauli", "Muku",
        ]
        start = date(2025, 2, 28)
        got = [po_mahina_name(*hawaiian_night(start + timedelta(days=i)))
               for i in range(30)]
        assert got == printed


class TestAnahulu:
    def test_boundaries(self):
        assert anahulu_name(1) == "hoʻonui"
        assert anahulu_name(10) == "hoʻonui"
        assert anahulu_name(11) == "poepoe"
        assert anahulu_name(20) == "poepoe"
        assert anahulu_name(21) == "hōʻemi"
        assert anahulu_name(30) == "hōʻemi"


class TestCounsel:
    """The vendored WPRFMC counsel stays keyed to real names."""

    def test_every_anahulu_has_counsel(self):
        assert set(ANAHULU_COUNSEL) == set(_ANAHULU)

    def test_every_note_names_a_real_night(self):
        assert set(_NIGHT_NOTES) <= set(_PO_MAHINA)

    def test_the_kapu_nights_as_the_display_draws_them(self):
        # Kapu Kū over Hilo..Kūlua, Hua over Mōhalu..Hua, Kāloa over
        # the first two Kāloa nights, Kāne over Kāne and Lono.
        assert night_note("Hilo").startswith("Kapu Kū")
        assert night_note("Kūlua").startswith("Kapu Kū")
        assert night_note("Kūkolu") is None
        assert night_note("Hua").startswith("Kapu Hua")
        assert night_note("Kāloakūlua").startswith("Kapu Kāloa")
        assert night_note("Kāloapau") is None
        assert night_note("Lono").startswith("Kapu Kāne")
        assert night_note("Mauli") is None
        assert night_note("ʻOlepau").startswith("ʻOle night")
