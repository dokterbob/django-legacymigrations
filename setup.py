#!/usr/bin/env python
from setuptools import setup, find_packages

try:
    README = open('README.rst').read()
except:
    README = None

try:
    REQUIREMENTS = open('requirements.txt').read()
except:
    REQUIREMENTS = None

setup(
    name = 'django-legacymigrations',
    version = "0.1",
    description = 'Continuous legacy database migrations using Django.',
    long_description = README,
    install_requires = REQUIREMENTS,
    author = '1%CLUB',
    author_email = 'devteam@1procentclub.nl',
    url = 'https://github.com/onepercentclub/django-legacymigrations/',
    packages = find_packages(),
    include_package_data = True,
    classifiers = ['Development Status :: 3 - Alpha',
                   'Environment :: Web Environment',
                   'Framework :: Django',
                   'Intended Audience :: Developers',
                   'License :: OSI Approved :: BSD License',
                   'Operating System :: OS Independent',
                   'Programming Language :: Python',
                   'Topic :: Utilities'],
)
