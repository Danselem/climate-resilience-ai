"""The ward plan: geometry, not geography.

No basemap. The sheet shows the municipality's own boundary line and fills each
ward by the indicator in view, which is what a plan extract does. Tiles would
add roads and labels the reader does not need, require a network, and make the
page look like every other GIS dashboard.
"""

from __future__ import annotations

import json
from pathlib import Path

import pydeck as pdk

from .presentation import quantile_bins, shade
from .theme import INK, PAPER, RULE

WARDS_PATH = Path(
    "data/processed/geoboundaries_zaf_adm4/adm4-2020/ethekwini-wards.geojson"
)
NO_DATA = "#D9D2C8"


def load_wards() -> dict:
    """Read the ward geometry once. Missing file is a deployment problem."""
    return json.loads(WARDS_PATH.read_text(encoding="utf-8"))


def build(
    values: dict[str, float],
    *,
    selected: str | None,
    colour: str,
) -> pdk.Deck:
    wards = load_wards()
    edges = quantile_bins(list(values.values()))
    features = []
    for feature in wards["features"]:
        ward_id = str(feature["properties"].get("ward_id", ""))
        value = values.get(ward_id)
        fill = _rgba(shade(value, edges, colour) if value is not None else NO_DATA)
        features.append(
            {
                **feature,
                "properties": {
                    **feature["properties"],
                    "fill": fill,
                    "value": value,
                    "has_value": value is not None,
                },
            }
        )

    layers = [
        pdk.Layer(
            "GeoJsonLayer",
            data={"type": "FeatureCollection", "features": features},
            stroked=True,
            filled=True,
            get_fill_color="properties.fill",
            get_line_color=list(_rgba(RULE)),
            line_width_min_pixels=0.6,
            pickable=True,
            auto_highlight=True,
            highlight_color=[21, 25, 27, 40],
        )
    ]
    if selected:
        chosen = [f for f in features if str(f["properties"].get("ward_id")) == selected]
        if chosen:
            layers.append(
                pdk.Layer(
                    "GeoJsonLayer",
                    data={"type": "FeatureCollection", "features": chosen},
                    stroked=True,
                    filled=False,
                    get_line_color=list(_rgba(INK)),
                    line_width_min_pixels=2.5,
                )
            )

    return pdk.Deck(
        layers=layers,
        initial_view_state=_view_state(wards),
        views=[pdk.View(type="MapView", controller=True)],
        map_style=None,
        tooltip={
            "html": "<b>{ward_name}</b><br/>{value}",
            "style": {"backgroundColor": PAPER, "color": INK, "fontSize": "12px"},
        },
    )


def _view_state(wards: dict) -> pdk.ViewState:
    lons: list[float] = []
    lats: list[float] = []
    for feature in wards["features"]:
        for ring in _rings(feature["geometry"]):
            for lon, lat in ring:
                lons.append(lon)
                lats.append(lat)
    return pdk.ViewState(
        longitude=(min(lons) + max(lons)) / 2,
        latitude=(min(lats) + max(lats)) / 2,
        zoom=8.4,
        pitch=0,
        bearing=0,
    )


def _rings(geometry: dict) -> list[list[list[float]]]:
    if geometry["type"] == "Polygon":
        return geometry["coordinates"]
    return [ring for polygon in geometry["coordinates"] for ring in polygon]


def _rgba(colour: str) -> list[int]:
    return [int(colour[index : index + 2], 16) for index in (1, 3, 5)] + [255]
