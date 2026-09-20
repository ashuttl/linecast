# Night lights

`night_lights.bin` is derived from NASA's **Black Marble 2016 grayscale** global map, using Suomi NPP VIIRS observations. It is a static historical composite, not live lighting or a map of current power outages. The terminator and cloud imagery are separate layers.

Source: [NASA Earth at Night / Black Marble flat maps](https://science.nasa.gov/earth/earth-observatory/earth-at-night/maps/), 2016 Grayscale, global 3600 × 1800 (0.1 degrees), [GeoTIFF](https://assets.science.nasa.gov/content/dam/science/esd/eo/images/imagerecords/144000/144897/BlackMarble_2016_01deg_gray_geo.tif).

Credit: NASA Earth Observatory images by Joshua Stevens, using Suomi NPP VIIRS data from Miguel Román, NASA GSFC. NASA imagery is generally available for reuse; see [NASA image and media usage guidelines](https://www.nasa.gov/nasa-brand-center/images-and-media/). These credits apply to the source imagery; the derived display treatment is Linecast's.

Source SHA-256: `35fd04c07eb69605e037ecca8f7ce43442a4a109bcac3a84df713661455c1ec8`.

Rebuild from the repository root with `uv run --with pillow scripts/build_night_lights.py`. For a downloaded copy, add `--source /path/to/BlackMarble_2016_01deg_gray_geo.tif`. Pillow is needed only to build the asset. The runtime uses the Python standard library and does not fetch night-light data.

The source covers longitude −180 to +180 from left to right and latitude +90 to −90 from top to bottom. The bake converts its equal RGB channels to grayscale and area-averages directly from the original into seven levels: 2048 × 1024 down to 32 × 16. It uses means, never peak pooling or population-based point placement. The file is zlib-compressed: `NL01`, a big-endian uint32 level count, then a big-endian uint32 width and height followed by row-major grayscale bytes for each level.

Both settled and moving maps sample the same pyramid bilinearly, wrap longitude, clamp latitude and blend between adjacent resolution levels. The projected pixel footprint chooses the level, with an approximate correction for the globe's limb and converging meridians. A display gamma of 0.65 makes concentrated lights readable; samples at or below one grayscale code value stay dark. The existing warm tint and daylight gate are applied afterward. This is a visual treatment of the published map, not calibrated radiance. At close zooms the lights fade out smoothly: full strength until a source texel spans two display sub-pixels, reaching zero at six. The fade follows angular resolution per display pixel, so it responds consistently to terminal size and zoom, and both moving and settled maps use the same treatment. Terrain remains visible throughout; no detailed light tiles are fetched.
