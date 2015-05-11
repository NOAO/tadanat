
use: postproc-bok.sh instead


#!/bin/bash
# PURPOSE: Stuff BOK fits files and generated options directly into 
#   valley queue.
#
# Examples:
#   stuff-bok.sh  #all files
#   stuff-bok.sh  /data/bok-real/20150411   # just one day
#
# ASSUMPTIONS:
#  - Submit all decendents of $bokdir that match "*.fits.fz"

bokdir=${1:-/data/bok-real}

mkdir /var/tada/mountain-mirror/tada
sudo chown tada /var/tada/mountain-mirror/tada
umask 0000

date

find $bokdir -name "*.fits.fz" -print0 \
    | xargs -0 -L 1 push_bok_with_options.sh 

dqcli -s
