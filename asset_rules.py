"""One source for uploader, compiler and artist-facing requirements."""
PIXEL_EDGE = 1022
EFFECT_EDGE = 2046
FILE_BYTES = 64 * 1024 * 1024
IMAGE_PIXELS = 32_000_000
RULES = {"formats": ["PNG"], "singleFileMiB": 64, "pixelEdge": PIXEL_EDGE,
         "effectEdge": EFFECT_EDGE, "maxTicks": 4096, "timebase": 60,
         "pixelAtlas": [1024, 4096], "effectAtlas": [2048, 4096]}
