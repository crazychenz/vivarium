#!/bin/sh

DEBUG_TAG=
if [ "$1" = "debug" ]; then
  DEBUG_TAG=-debug
fi

docker run -ti --rm agent:distroless$(DEBUG_TAG)
