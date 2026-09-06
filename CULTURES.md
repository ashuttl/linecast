# The sky's cultures

`linecast sky` draws the IAU's eighty-eight constellations by default, with the star names the IAU has settled on. Twenty-two other traditions are bundled, each with its own figures and, where the tradition names stars, its own star names. `t` steps through them live, `sky --culture NAME` opens on one, and `linecast culture NAME` saves one for every run. Chinese comes with the language: `--lang zh` draws the Chinese sky unless told otherwise, the way the moon follows the Chinese calendar.

The figures and names are from [Stellarium's sky-culture collection](https://github.com/Stellarium/stellarium-skycultures), which gathers the work of many contributors under each culture's own licence. linecast bundles the ones whose text and lines are under a Creative Commons licence that allows redistribution and derived work, CC BY or CC BY-SA. The Arabic cultures (no-derivatives), the Kamilaroi and Lokono (non-commercial), and the GPL-licensed ones (Aztec, Egyptian, Inuit, Korean, Macedonian, Navajo, Northern Andes, Sardinian, Tupi) are not bundled; their absence is a matter of licence, not of interest. Stellarium's own descriptions of each culture, with their references, are the place to read more.

The figures join stars by Hipparcos number; linecast places them from the Hipparcos main catalogue (ESA, CDS I/239) and matches the named stars to its own Yale Bright Star Catalogue by HD number, so a name for a star fainter than magnitude 6.5 is not shown. What each culture calls a figure is shown in the culture's own language where the display language is that language (Chinese in Chinese, Ruelle's French in French), and otherwise in the English the contributors gave, or the native name where there is no English. The `t` key's status line names the culture; the pointer's chip gives a star's IAU name beside the culture's.

The data file, `src/linecast/data/cultures.json.gz`, is a derived work of these sources and is offered under CC BY-SA 4.0 with the credits below. Everything else in linecast stays MIT.

| Name | Culture | Region | Figures | Star names | Credits | Licence |
| --- | --- | --- | --- | --- | --- | --- |
| `anutan` | Anutan | Oceania | 11 | 2 | Contributed by Doina Bucur, digitised for *The network signature of constellation line figures*; an earlier version by Dan Smale | CC BY-SA |
| `belarusian` | Belarusian | Europe | 20 | 2 | Text and data by Alexander Wolf, Tsimafei Avilin and Johan Meuris | CC BY-SA |
| `blackfoot` | Blackfoot | America | 4 | 3 | Contributed by Doina Bucur, digitised for *The network signature of constellation line figures* | CC BY-SA |
| `boorong` | Boorong | Oceania | 29 | 25 | Contributed by John Morieson and Alex Cherney; technical rework by Susanne M. Hoffmann | CC BY-SA |
| `bugis` | Bugis | Asia | 12 | 4 | Contributed by Doina Bucur, digitised for *The network signature of constellation line figures* | CC BY-SA |
| `chinese` | Chinese | Asia | 312 | 2759 | Initially contributed by Karrie Berglund of Digitalis Education Solutions, from the Hong Kong Space Museum star maps; more than 200 xingguan and 3,000 stars by Sun Shuwei, after Yi Shitong's *Chinese and Western Contrast Star Chart and Catalogue 1950.0*; text rework by the Stellarium team | CC BY-SA |
| `chinese-modern` | Chinese Contemporary | Asia | 88 | 2759 | Contributed by Sun Shuwei and reworked by the Stellarium team: the IAU figures with the traditional Chinese star names | CC BY-SA |
| `hawaiian` | Hawaiian star lines | Oceania | 13 | 68 | Contributed in 2017 by teachers Darren Kamalu and Christopher Blake, students Jonah Apo, Nicholas Koanui and Brenden Aila, and the Celestial Navigation class at Kamehameha Schools Kapālama, Honolulu; reworked by Susanne M. Hoffmann | CC BY-SA |
| `indian` | Indian Vedic | Asia | 28 | 31 | Tanmoy Saha, Vishvas Vasuki and contributors from the sanskrit-coders community; reworked by Susanne M. Hoffmann | CC BY-SA |
| `japanese` | Japanese lunar stations | Asia | 28 | 0 | Text and data by Alexander Wolf; clean-up by Susanne M. Hoffmann and the Stellarium team | CC BY-SA |
| `mandar` | Mandar | Asia | 6 | 0 | Contributed by Doina Bucur, digitised for *The network signature of constellation line figures* | CC BY-SA |
| `maori` | Māori | Oceania | 6 | 24 | Contributed by Dan Smale | CC BY-SA |
| `mongolian` | Mongolian | Asia | 4 | 9 | Contributed by Anthony Lagain and Batiste Rousseau, from oral tales gathered over two months in Mongolia; reworked by Susanne M. Hoffmann | CC BY-SA |
| `norse` | Norse | Europe | 6 | 3 | Contributed by Jonas Persson; description by Susanne M. Hoffmann | CC BY-SA |
| `romanian` | Romanian | Europe | 39 | 8 | Contributed by Mircea Lite for the Baia Mare Planetarium's *Traditional Romanian Constellations* project (2012–2013), after Ion Ottescu's *Romanian peasants' beliefs in stars and sky* | CC BY-SA |
| `ruelle` | Ruelle (France, 1786) | Europe | 70 | 0 | Contributed by Doina Bucur, digitised for *The network signature of constellation line figures* | CC BY-SA |
| `sami` | Sami | Europe | 10 | 0 | Contributed by Jonas Persson; technical rework by Susanne M. Hoffmann | CC BY-SA |
| `siberian` | Siberian | Asia | 3 | 1 | Text and data by Alexander Wolf; text adapted by Susanne M. Hoffmann | CC BY-SA |
| `tongan` | Tongan | Oceania | 11 | 7 | Contributed by Dan Smale; technical adaptation by Susanne M. Hoffmann | CC BY-SA |
| `tukano` | Tukano | America | 11 | 0 | Gathered by Walmir Thomazi Cardoso in the survey for his PhD thesis in ethnomathematics; technical adaptation by the Stellarium team | CC BY-SA |
| `snt` | Western, Sky & Telescope figures | Europe | 88 | 0 | Paul Krizak and Jonathan E. Piskor; rework by the Stellarium team | CC BY-SA 2.0 |
| `rey` | Western, H. A. Rey's figures | Europe | 171 | 2 | Mike Richards and Georg Zotti, after the 41st reprint of *The Stars: A New Way to See Them* | CC BY-SA |

With the Hawaiian culture the horizon carries the star compass in place of the compass points: Nainoa Thompson's thirty-two houses of 11.25°, the cardinal houses ʻĀkau, Hikina, Hema and Komohana in bold, and in each quadrant the seven houses named alike from the east or west point toward the pole, Lā, ʻĀina, Noio, Manu, Nālani, Nāleo and Haka. The status line names the house faced with its quadrant, the winds Koʻolau, Malanai, Kona and Hoʻolua, and the pointer's chip gives a star's house. The houses and their order are the Polynesian Voyaging Society's, from its description of [the star compass](https://worldwidevoyage.hokulea.com/education-at-sea/polynesian-navigation/the-star-compass/).

The two Western entries keep the IAU constellations and change only the figures: Sky & Telescope's are the ones its charts use, and H. A. Rey's are the stick figures from *The Stars*, drawn so the shapes look like their names. The Chinese entry is the traditional sky of the Three Enclosures and Twenty-Eight Mansions; Chinese Contemporary keeps the IAU figures and puts the traditional Chinese star names on them. The Japanese lunar stations are the twenty-eight *sei shuku*, the Chinese mansions as Japan drew them.
