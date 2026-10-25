#!/usr/bin/env bash

[ -f "state/run/alpine-agent.pid" ] && ( kill "$(cat state/run/alpine-agent.pid)"; rm -f state/run/alpine-agent.pid )

