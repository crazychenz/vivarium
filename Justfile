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
    pip install -U -r requirements.txt
    pip install -U -e ./packages/thirdparty_vivarium
#    pip install -U -e ./packages/thirdparty_dalvik
#    pip install -U -e ./packages/thirdparty_jdwp
#    pip install -U -e ./packages/thirdparty_android
#    pip install -U -e ./packages/thirdparty_apkd