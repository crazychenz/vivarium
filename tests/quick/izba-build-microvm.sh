#!/bin/sh

IZBA_FLAGS=$1

izba $IZBA_FLAGS build --driver microvm -t microvm_test_img \
&& izba $IZBA_FLAGS create --name microvm_test_inst microvm_test_img \
&& izba $IZBA_FLAGS start microvm_test_inst \
&& izba $IZBA_FLAGS exec microvm_test_inst -- cat /etc/passwd

#&& izba $IZBA_FLAGS stop microvm_test_inst \
# && izba $IZBA_FLAGS rm microvm_test_inst \
# && izba $IZBA_FLAGS rmi microvm_test_img