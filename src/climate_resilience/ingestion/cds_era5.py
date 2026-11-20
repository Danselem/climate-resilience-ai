"""Alert: the Copernicus CDS adapter is declared, not implemented.

The production ERA5 path requires a CDS account and licence acceptance.
Rather than write a client that cannot be exercised, this module states the
contract the adapter must satisfy. Until it exists, `era5_openmeteo` is the
only climate source and its provenance is labelled as such in every envelope.
"""

CDS_DATASET = "reanalysis-era5-single-levels"
CDS_VARIABLES = ("2m_temperature",)
EXPECTED_OUTPUT = "NetCDF, subset to the metro bounding box, one file per decade"


def not_implemented() -> None:
    raise NotImplementedError(
        "CDS ERA5 adapter requires credentials (CDSAPI_RC) and licence acceptance. "
        "Implement before claiming ERA5 provenance directly from Copernicus."
    )
