"""Collect real contact details as people typed them: OpenStreetMap places.

    python3 studies/real-text/collect_osm.py
    python3 studies/real-text/collect_osm.py --held-out

For the centre of each city in CITIES this asks the public Overpass API for
every element that carries a phone number or an email address, as the map
stood at SNAPSHOT, and stores the reply in studies/real-text/cache/osm/. The
values are what mappers and business owners entered by hand, in whatever
format is usual where they live, and the tag key says what each value is.
That is the gold label: nobody had to annotate anything.

The data is (c) OpenStreetMap contributors, under the Open Database License
(https://www.openstreetmap.org/copyright). It is not committed here. What is
committed is manifest-osm.json: the query, the snapshot date, and for each
city the number of elements and the SHA-256 of the reply.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
ENDPOINT = "https://overpass-api.de/api/interpreter"
MIRROR = "https://maps.mail.ru/osm/tools/overpass/api/interpreter"
SNAPSHOT = "2026-10-01T00:00:00Z"
USER_AGENT = "veil-study/1.0 (https://github.com/antonsoo/veil; anton@praviel.com)"

# (ISO country, city, south, west, north, east): a few square kilometres of the centre.
CITIES = (
    ("US", "New York", 40.740, -74.000, 40.770, -73.965),
    ("US", "Chicago", 41.870, -87.650, 41.900, -87.615),
    ("US", "Austin", 30.255, -97.760, 30.290, -97.725),
    ("CA", "Toronto", 43.640, -79.400, 43.670, -79.370),
    ("MX", "Mexico City", 19.420, -99.180, 19.445, -99.150),
    ("BR", "São Paulo", -23.565, -46.665, -23.540, -46.630),
    ("AR", "Buenos Aires", -34.610, -58.390, -34.590, -58.365),
    ("GB", "London", 51.500, -0.150, 51.525, -0.100),
    ("IE", "Dublin", 53.335, -6.280, 53.355, -6.240),
    ("FR", "Paris", 48.850, 2.330, 48.875, 2.370),
    ("DE", "Berlin", 52.505, 13.370, 52.530, 13.420),
    ("NL", "Amsterdam", 52.360, 4.880, 52.380, 4.910),
    ("ES", "Madrid", 40.405, -3.715, 40.430, -3.685),
    ("IT", "Rome", 41.890, 12.470, 41.910, 12.500),
    ("PL", "Warsaw", 52.220, 21.000, 52.245, 21.030),
    ("SE", "Stockholm", 59.325, 18.050, 59.340, 18.080),
    ("ZA", "Cape Town", -33.935, 18.410, -33.915, 18.430),
    ("IN", "Bengaluru", 12.960, 77.580, 12.990, 77.620),
    ("SG", "Singapore", 1.280, 103.840, 1.305, 103.860),
    ("JP", "Tokyo", 35.675, 139.755, 35.700, 139.780),
    ("KR", "Seoul", 37.555, 126.970, 37.575, 126.995),
    ("AU", "Sydney", -33.880, 151.195, -33.860, 151.215),
)
# Collected only after the detectors were changed, and not looked at before
# the numbers were final: other cities, fifteen of them in other countries.
HELD_OUT = (
    ("US", "Los Angeles", 34.035, -118.270, 34.065, -118.235),
    ("CA", "Vancouver", 49.270, -123.135, 49.290, -123.100),
    ("CO", "Bogotá", 4.595, -74.085, 4.620, -74.060),
    ("CL", "Santiago", -33.450, -70.670, -33.425, -70.640),
    ("GB", "Manchester", 53.470, -2.255, 53.490, -2.225),
    ("FR", "Lyon", 45.750, 4.820, 45.775, 4.850),
    ("DE", "Munich", 48.130, 11.560, 48.150, 11.590),
    ("AT", "Vienna", 48.200, 16.360, 48.220, 16.385),
    ("CH", "Zurich", 47.365, 8.530, 47.385, 8.555),
    ("BE", "Brussels", 50.840, 4.340, 50.860, 4.370),
    ("ES", "Barcelona", 41.380, 2.160, 41.400, 2.185),
    ("PT", "Lisbon", 38.705, -9.150, 38.725, -9.125),
    ("IT", "Milan", 45.455, 9.175, 45.475, 9.200),
    ("DK", "Copenhagen", 55.670, 12.560, 55.690, 12.590),
    ("CZ", "Prague", 50.075, 14.415, 50.095, 14.440),
    ("TR", "Istanbul", 41.025, 28.970, 41.045, 28.995),
    ("KE", "Nairobi", -1.295, 36.810, -1.275, 36.835),
    ("TH", "Bangkok", 13.735, 100.520, 13.760, 100.545),
    ("ID", "Jakarta", -6.200, 106.815, -6.175, 106.840),
    ("HK", "Hong Kong", 22.275, 114.150, 22.290, 114.180),
    ("TW", "Taipei", 25.035, 121.505, 25.060, 121.530),
    ("JP", "Osaka", 34.690, 135.490, 34.710, 135.515),
    ("AU", "Melbourne", -37.825, 144.950, -37.805, 144.975),
    ("NZ", "Auckland", -36.860, 174.755, -36.840, 174.780),
)
KEYS = ("phone", "contact:phone", "email", "contact:email")


def query(south: float, west: float, north: float, east: float) -> str:
    box = f"({south},{west},{north},{east})"
    wanted = "".join(f'nwr["{key}"]{box};' for key in KEYS)
    return f'[out:json][timeout:180][date:"{SNAPSHOT}"];({wanted});out tags center;'


def slug(country: str, city: str) -> str:
    return f"{country}-{city}".lower().replace(" ", "-").replace("ã", "a").replace("á", "a")


def fetch(text: str) -> bytes:
    body = urllib.parse.urlencode({"data": text}).encode()
    for attempt in range(12):
        # The main instance sheds load with 429 and 504; after three refusals
        # in a row a public mirror with the same history takes a turn.
        endpoint = ENDPOINT if attempt % 6 < 3 else MIRROR
        request = urllib.request.Request(endpoint, data=body, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=240) as response:
                return response.read()
        except OSError as error:
            wait = min(120, 20 * (attempt + 1))
            print(f"  {endpoint.split('/')[2]}: {error}; waiting {wait}s")
            time.sleep(wait)
    raise SystemExit("Overpass did not answer")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--held-out", action="store_true", help="collect the held-out cities instead"
    )
    args = parser.parse_args()
    chosen, name = (
        (HELD_OUT, "manifest-osm-heldout.json") if args.held_out else (CITIES, "manifest-osm.json")
    )

    cache = HERE / "cache" / "osm"
    cache.mkdir(parents=True, exist_ok=True)
    cities = []
    for country, city, south, west, north, east in chosen:
        target = cache / f"{slug(country, city)}.json"
        if not target.exists():
            target.write_bytes(fetch(query(south, west, north, east)))
            time.sleep(8)
        raw = target.read_bytes()
        elements = json.loads(raw)["elements"]
        cities.append(
            {
                "country": country,
                "city": city,
                "bbox": [south, west, north, east],
                "file": target.name,
                "elements": len(elements),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
        print(f"{country} {city}: {len(elements):,} elements")
    manifest = {
        "source": "OpenStreetMap via the Overpass API",
        "licence": "Open Database License 1.0, (c) OpenStreetMap contributors",
        "endpoint": ENDPOINT,
        "snapshot": SNAPSHOT,
        "query": query(0, 0, 0, 0).replace("(0,0,0,0)", "(south,west,north,east)"),
        "cities": cities,
    }
    (HERE / name).write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
