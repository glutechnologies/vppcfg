"""vppcfg setuptools setup.py for pip and deb pkg installations"""

import os
from setuptools import setup

# Read version from _version.py
version_file = os.path.join(os.path.dirname(__file__), "vppcfg", "_version.py")
with open(version_file) as f:
    exec(f.read())

setup(
    name="vppcfg",
    version=__version__,
    install_requires=[
        "requests",
        'importlib-metadata; python_version >= "3.8"',
        "yamale",
        "netaddr",
        "vpp_papi",
    ],
    packages=["vppcfg", "vppcfg/config", "vppcfg/vpp"],
    entry_points={
        "console_scripts": [
            "vppcfg = vppcfg.vppcfg:main",
        ]
    },
    test_suite="vppcfg.config",
    package_data={"vppcfg": ["*.yaml"]},
)
