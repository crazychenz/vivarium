#!/bin/sh

DEBUG_TAG=
DEBUG_ARG=
ARG=$1
if [ "${ARG}" = "debug" ]; then
  DEBUG_TAG=-debug
  DEBUG_ARG=debug-
fi

docker build -t agent:distroless$DEBUG_TAG --build-arg DEBUG_ARG="${DEBUG_ARG}" -f distroless.dockerfile distroless