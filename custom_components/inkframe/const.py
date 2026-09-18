"""Constants for the InkFrame integration.

The integration talks to services/ImmichFrame, the renderer, never to the
panel: the panel is a battery ESP32-C3 in deep sleep for all but ~35 seconds a
week. Everything set here takes effect at the panel's next wake, and
`binary_sensor.*_on_panel` is the only entity that says whether it did.
"""
DOMAIN = "inkframe"

CONF_URL = "url"
CONF_TOKEN = "token"
CONF_SCAN_SECONDS = "scan_seconds"

DEFAULT_URL = "http://immich-frame:8099"
DEFAULT_SCAN_SECONDS = 300
MIN_SCAN_SECONDS = 60

HTTP_TIMEOUT_SECONDS = 20
# /next downloads and scores twenty candidates before answering.
NEXT_TIMEOUT_SECONDS = 180

# Select labels. The server speaks "random" / "recent:90d" / "person:Name" /
# "people:A,B" / "album:Name"; these are the fixed human labels.
SOURCE_RANDOM = "Random"
SOURCE_RECENT = "Recent"
SOURCE_PEOPLE = "People"
SOURCE_ALBUM = "Album"
SOURCE_SEARCH = "Search"
NO_ALBUMS = "(no albums in Immich)"

# Settings exposed as numbers. Contrast and candidates are deliberately NOT
# here (decided 2026-09-17): contrast overlaps the tone curve, and twenty
# candidates is right -- more only costs time. Both stay settable on the server
# by environment variable.
#
# Sleep interval and OTA window were firmware substitutions until 2026-09-17.
# They now travel to the panel in the /wake reply, so changing them here needs
# no reflash and takes effect from the wake after next.
#
#   key, name, min, max, step, entity_category ("config" hides it behind the
#   device page's settings section), icon, unit
NUMBER_SETTINGS: tuple[tuple[str, str, float, float, float, str | None, str, str | None], ...] = (
    ("max_busyness", "Max busyness", 1, 100, 0.5, None, "mdi:blur", None),
    ("sleep_hours", "Sleep interval", 1, 336, 1, None, "mdi:sleep", "h"),
    ("ota_window_seconds", "OTA window", 5, 300, 5, "config", "mdi:update", "s"),
    ("smooth", "Smooth", 0, 1, 0.05, "config", "mdi:blur-linear", None),
    ("curve", "Tone curve", 0, 1, 0.05, "config", "mdi:chart-bell-curve-cumulative", None),
    ("edge", "Edge", 0, 200, 5, "config", "mdi:image-filter-center-focus", None),
)

MIN_RECENT_DAYS = 7
MAX_RECENT_DAYS = 365
