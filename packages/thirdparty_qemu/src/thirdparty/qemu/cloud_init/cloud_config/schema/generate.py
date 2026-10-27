"""Regenerate ../models.py from schema-cloud-config-v1.json (needs datamodel-code-generator)."""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

here = Path(__file__).parent
schema = json.loads((here / "schema-cloud-config-v1.json").read_text())

# Invalid upstream: enum must be a list, use a $ref instead.
schema["$defs"]["modules_definition"]["items"]["oneOf"][1]["prefixItems"][0] = {
    "$ref": "#/$defs/all_modules"
}
# Dotted def names make datamodel-codegen want a modular output directory.
text = re.sub(
    r"#/\$defs/([A-Za-z0-9_.]+)",
    lambda m: "#/$defs/" + m.group(1).replace(".", "_"),
    json.dumps(schema),
)
schema = json.loads(text)
schema["$defs"] = {k.replace(".", "_"): v for k, v in schema["$defs"].items()}

with tempfile.TemporaryDirectory() as tmp:
    fixed = Path(tmp) / "schema.json"
    fixed.write_text(json.dumps(schema))
    subprocess.run(
        [
            sys.executable, "-W", "ignore", "-m", "datamodel_code_generator",
            "--input", str(fixed), "--input-file-type", "jsonschema",
            "--output-model-type", "pydantic_v2.BaseModel",
            "--use-annotated", "--use-union-operator", "--target-python-version", "3.10",
            "--field-constraints", "--use-standard-collections", "--base-class", "thirdparty.qemu.cloud_init.base.CloudBase",
            "--class-name", "CloudConfig", "--formatters", "black", "isort",
            "--output", str(here.parent / "lib.py"),
        ],
        check=True,
    )
