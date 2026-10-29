"""Pydantic models for cloud-init ``#cloud-config`` user-data.

``lib.py`` is generated from ``schema/schema-cloud-config-v1.json`` by
``schema/generate.py``. Do not edit it by hand.
"""

import yaml

from .models import *

__all__ = ["CloudConfig", "to_yaml"]

class IndentDumper(yaml.SafeDumper):
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)   # never use "indentless" sequences


def cloud_config_to_yaml(config: CloudConfig) -> str:
    """Render a CloudConfig as a ``#cloud-config`` document (only fields that were set)."""
    data = config.model_dump(mode="json", by_alias=True, exclude_unset=True, exclude_none=True)
    #return "#cloud-config\n" + yaml.safe_dump(data, sort_keys=False)
    return "#cloud-config\n" + yaml.dump(data, Dumper=IndentDumper, sort_keys=False, default_flow_style=False)

