#!/usr/bin/env bash

DURATION=full
if [ $# -lt 1 ]; then
  echo $0 "<days|full|all>"
  exit 0
else
  DURATION=$1
fi

export PROJ_PATH=${PROJ_PATH:-$(realpath $(dirname $0)/..)}
export BUNDLE_PATH=${PROJ_PATH}/cache/bundles
DAY_SECS=$(( $(date +%s) - $(date +%s -d "$(date +%Y-%m-%d) 00:00:00") ))
SECS_ATETH=$(printf '%x' $(( ($DAY_SECS) / 8 )))
FPATH=${BUNDLE_PATH}/vivarium-$(date +%Y%m%d)-${SECS_ATETH}

mkdir -p ${BUNDLE_PATH}

case "$DURATION" in

  ''|*[!0-9]*)
    if [ "$DURATION" == "full" -o "$DURATION" == "all" ]; then
      echo Bundle everything
      git bundle create ${FPATH}-full.bundle --all
      base64 ${FPATH}-full.bundle > ${FPATH}-full.bundle.base64.txt
      echo "Created: ${FPATH}-full.bundle.base64.txt"
    else
      echo $0 "<days|full|all> dfg"
      exit 0
    fi
    ;;

  *)
    echo Bundle number of given days
    git bundle create ${FPATH}-${DURATION}days.bundle --all \
      --since="${DURATION} days ago"
    base64 ${FPATH}-${DURATION}days.bundle > ${FPATH}-${DURATION}days.bundle.base64.txt
    echo "Created: ${FPATH}-${DURATION}days.bundle.base64.txt"
    ;;

esac


