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
    # For now we pull from trunk until the Python 3.14 fix is versioned.
    pip install -U "git+https://github.com/fox-it/dissect.target.git@main"
    pip install -U -r requirements.txt
    pip install -U -e ./packages/thirdparty_qemu
    pip install -U -e ./packages/thirdparty_dockerfile
    pip install -U -e ./packages/thirdparty_vivarium

#    pip install -U -e ./packages/thirdparty_dalvik
#    pip install -U -e ./packages/thirdparty_jdwp
#    pip install -U -e ./packages/thirdparty_android
#    pip install -U -e ./packages/thirdparty_apkd


# alias iso_ls='7z l ' && alias iso_cat='7z x -so '