"""vppcfg setuptools setup.py for pip and deb pkg installations"""

import os
from setuptools import setup

# Read version from _version.py
version_file = os.path.join(os.path.dirname(__file__), "vppcfg", "_version.py")
with open(version_file) as f:
    exec(f.read())

setup(
    version=__version__,
    packages=["vppcfg", "vppcfg/config", "vppcfg/vpp"],
    package_data={"vppcfg": ["*.yaml"]},
)
