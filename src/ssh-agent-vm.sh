#!/bin/sh

exec ssh -p 2223 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null agent@127.0.0.1

