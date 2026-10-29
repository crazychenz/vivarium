# Source Maintenance Targets

bundle DURATION="":
    ./scripts/create-bundle.sh {{DURATION}}

#builddevpkgs TAG="":
#    ./scripts/build-dev-pkgs.sh {{TAG}}

#buildpkgs TAG="":
#    ./scripts/build-pkgs.sh {{TAG}}

#pytests *args:
#    ./scripts/pytests.sh {{args}}

#builddocs:
#    ./docs/builders/api/build-docs.sh
#    ./docs/builders/pandoc/build-docs.sh
#    ./docs/builders/docusaurus/build-docs.sh

devinstall:
    # --- dissect.target fix ---
    # For now we pull dissect.target from trunk until the Python 3.14 fix is versioned.
    # pip does not cache clones, so each run is slow.
    # Slow Command: pip install -U "git+https://github.com/fox-it/dissect.target.git@main"
    # Instead, we'll keep our own clone and install from it.
    # Faster local cache:
    d=~/.cache/dissect.target.git; { [ -d "$d/.git" ] && git -C "$d" pull --ff-only || git clone https://github.com/fox-it/dissect.target.git "$d"; }
    pip install -U ~/.cache/dissect.target.git
    # --- dissect.target fix ---

    pip install -U -r requirements.txt
    pip install -U -e ./packages/thirdparty_qemu
    pip install -U -e ./packages/thirdparty_dockerfile
    pip install -U -e ./packages/thirdparty_vivarium

#    pip install -U -e ./packages/thirdparty_dalvik
#    pip install -U -e ./packages/thirdparty_jdwp
#    pip install -U -e ./packages/thirdparty_android
#    pip install -U -e ./packages/thirdparty_apkd


# alias iso_ls='7z l ' && alias iso_cat='7z x -so '