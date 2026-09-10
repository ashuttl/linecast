"""Bake Messier objects from d3-celestial's BSD-licensed data.

    python scripts/build_sky_objects.py --from DIR

DIR holds messier.json and dsonames.json from
https://github.com/ofrohn/d3-celestial/tree/master/data .
Exclude M40/M73 (stars/asterisms) and M24 (a Milky Way star cloud already
in the background). Dimensions are arcminutes, coordinates J2000 degrees.
"""

import argparse
import gzip
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / 'src/linecast/data'


def bake(src):
    names = json.loads((src / 'dsonames.json').read_text())
    records = []
    for feature in json.loads((src / 'messier.json').read_text())['features']:
        p = feature['properties']
        if p['type'] == 'pos':
            continue
        ident = feature['id']
        aliases = names.get(p['desig'], names.get(ident.replace('M', 'M '), {}))
        dims = [float(n) for n in p['dim'].split('x')]
        ra, dec = feature['geometry']['coordinates']
        records.append(dict(id=ident, designation=p['desig'],
                            name=aliases.get('name') or p['alt'] or ident,
                            aliases=[p['alt']] if p['alt'] else [],
                            names={k: v for k, v in aliases.items() if k != 'name'},
                            ra=ra % 360, dec=dec, mag=p['mag'], type=p['type'],
                            size=[dims[0], dims[-1]]))
    # Major-axis position angle east of celestial north: Hodge's M31 atlas,
    # https://ned.ipac.caltech.edu/level5/ANDROMEDA_Atlas/Hodge_intro.html
    # Other objects use circular schematic glows, without invented orientations.
    next(r for r in records if r['id'] == 'M31')['pa'] = 37.7
    out = DATA / 'sky-objects.json.gz'
    out.write_bytes(gzip.compress(json.dumps(records, ensure_ascii=False,
                                             separators=(',', ':')).encode(), mtime=0))
    print(f'{len(records)} deep-sky objects; {out.stat().st_size:,} bytes')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from', dest='src', type=Path, required=True)
    bake(parser.parse_args().src)
