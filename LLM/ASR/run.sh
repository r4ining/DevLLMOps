#!/bin/bash 

set -x

python3 voxtral-realtime-verify.py --host 10.10.249.5 --port 30003 --model voxtral-mini-4b-realtime-2602 --audio-path demo-1.wav

