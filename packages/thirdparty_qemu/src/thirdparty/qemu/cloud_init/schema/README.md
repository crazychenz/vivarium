`models.py` is generated from the schema. The upstream schema needs two fixes first
(a `{"enum": {"$ref": ...}}` in `modules_definition`, and dots in `$defs` names, which
make datamodel-codegen emit modular output). Regenerate with:

    python schema/generate.py
