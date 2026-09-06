# Star data

`stars.bin` is the Yale Bright Star Catalogue, 5th revised edition (Hoffleit & Warren, 1991), through visual magnitude 6.5: 8,404 stars. It is built by `scripts/build_sky_catalogue.py` from http://tdc-www.harvard.edu/catalogs/bsc5.dat.gz. The existing names and cultures refer to indices in this file.

`stars-deep.bin.gz` is an adaptation of **HYG v4.1 by David Nash / Astronexus**, https://github.com/astronexus/HYG-Database, now maintained at https://codeberg.org/astronexus/hyg. HYG combines Hipparcos, Yale and Gliese data. The source and this adapted data file are licensed under **Creative Commons Attribution-ShareAlike 4.0 International**, https://creativecommons.org/licenses/by-sa/4.0/. This data licence applies to the supplement; the application code retains its own licence.

Changes made by linecast: select 108,520 stars fainter than the Yale limit, through visual magnitude 12.0; remove matches to the bundled Yale stars by HR or HD identifier; convert J2000 right ascension from hours to degrees; quantize positions to 0.001 degree, visual magnitude to 0.1 and B−V to 0.02; use neutral colour where HYG has none; retain HIP identifiers (HYG identifiers where HIP is absent); omit other fields; arrange records in spatial bins and compress. Stars whose magnitude rounds to 6.5 are omitted from the supplement. The selection is not a complete survey to magnitude 12. Individual faint stars are recorded to that depth, with coverage set by HYG's source catalogues. Positions are fixed at J2000; runtime proper motion and precession are not applied.

Rebuild with `python scripts/build_deep_stars.py --from DIR`. Put `bsc5.dat.gz` and [hygdata_v41.csv](https://raw.githubusercontent.com/astronexus/HYG-Database/main/hyg/CURRENT/hygdata_v41.csv) in that directory. The script documents the binary format; the embedded header records SHA-256 hashes of both source files. The output is deterministic. The application reads the bundled file offline, only when a magnified dark sky needs it.

# Extended objects

`sky-objects.json.gz` contains 107 Messier objects adapted from Olaf Frohn's d3-celestial `messier.json` and `dsonames.json`, https://github.com/ofrohn/d3-celestial/tree/master/data. The data is redistributed under the BSD 3-Clause licence reproduced below. The build selects positions, integrated magnitudes, angular dimensions, object types and names; converts negative RA to 0–360°; and excludes M24 (already represented in the Milky Way layer), M40 and M73 (stars/asterisms). Rebuild with `python scripts/build_sky_objects.py --from DIR`.

The glows are schematic, not astrophotographs or predictions of naked-eye visibility. Andromeda's major-axis position angle, 37.7° east of celestial north, comes from [Paul Hodge's Atlas of the Andromeda Galaxy, introduction, Table 1](https://ned.ipac.caltech.edu/level5/ANDROMEDA_Atlas/Hodge_intro.html) (1981; citing de Vaucouleurs 1958). Other extended objects use circular glows of the same elliptical area because this source does not provide orientations. Open clusters keep their constituent catalogued stars, with labels and hover regions but no diffuse glow.

Copyright (c) 2015, Olaf Frohn
All rights reserved.

Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its contributors may be used to endorse or promote products derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
