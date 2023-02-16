#!/bin/bash

python3 -m pip install --user twine wheel
python3 setup.py bdist_wheel
python3 -m twine upload dist/*
rm -rf release
