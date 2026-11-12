#!/bin/sh

IZBA_FLAGS=$1

izba $IZBA_FLAGS build --driver crt -t crt_test_img \
&& izba $IZBA_FLAGS create --name crt_test_inst crt_test_img \
&& izba $IZBA_FLAGS start crt_test_inst \
&& izba $IZBA_FLAGS exec crt_test_inst -- cat /etc/passwd \
&& izba $IZBA_FLAGS stop crt_test_inst \
&& izba $IZBA_FLAGS rm crt_test_inst \
&& izba $IZBA_FLAGS rmi crt_test_img