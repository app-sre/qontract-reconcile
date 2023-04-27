#!/bin/bash

python3 -m pip install --user urllib3==1.26.15 twine wheel
python3 setup.py bdist_wheel
python3 -m twine upload dist/*
