#!/bin/sh -u

# Go to current directory
cd `dirname $0`

PWD=`pwd`
BASEPATH=`basename $PWD`

GIT=git
PIP="pip --timeout 30 -q"
ENVDIR=env

SETTINGS_DIR=$PWD/bluebottle/settings
MANAGE_PY="$ENVDIR/bin/python ./manage.py"

PYPY_VERSION="1.9"
PYPY_FILE="pypy-$PYPY_VERSION-linux64.tar.bz2"
PYPY_DIR="pypy-$PYPY_VERSION"

# Patches / modifications to PyPy
PYPY_GZIP_PATCH="$PWD/patches/pypy-$PYPY_VERSION-fix-for-gzipfile-error.patch"
PYPY_URLLIB2_PATCH="$PWD/patches/pypy-$PYPY_VERSION-update-urllib2-from-python-2.7.3.patch"
PYPY_PSYCOPG_FILE="$PWD/patches/psycopg2.py"

# Require virtualenv >= 1.7.1.2. The version requirement comes from what's
# available in Ubuntu 12.04. Other versions might work as well.
which virtualenv
if [ $? -eq 0 ]; then
    REQUIRED_VIRTUALENV_VERSION=1.7.1.2
    OS_VIRTUALENV_VERSION=`virtualenv --version`

    # Version calculation code from here:
    # http://rubinium.org/blog/archives/2010/04/05/shell-script-version-compare-vercmp/
    RESULT=`expr '(' "$OS_VIRTUALENV_VERSION" : '\([^.]*\)' ')' '-' '(' "$REQUIRED_VIRTUALENV_VERSION" : '\([^.]*\)' ')' '|' \
    '(' "$OS_VIRTUALENV_VERSION.0" : '[^.]*[.]\([^.]*\)' ')' '-' '(' "$REQUIRED_VIRTUALENV_VERSION.0" : '[^.]*[.]\([^.]*\)' ')' '|' \
    '(' "$OS_VIRTUALENV_VERSION.0.0" : '[^.]*[.][^.]*[.]\([^.]*\)' ')' '-' '(' "$REQUIRED_VIRTUALENV_VERSION.0.0" : '[^.]*[.][^.]*[.]\([^.]*\)' ')' '|' \
    '(' "$OS_VIRTUALENV_VERSION.0.0.0" : '[^.]*[.][^.]*[.][^.]*[.]\([^.]*\)' ')' '-' '(' "$REQUIRED_VIRTUALENV_VERSION.0.0.0" : '[^.]*[.][^.]*[.][^.]*[.]\([^.]*\)' ')'`

    if [ $RESULT -lt 0 ]; then
        echo "Please install virtualenv >= $REQUIRED_VIRTUALENV_VERSION."
        exit 1
    fi
else
    echo "Please install virtualenv with your package manager."
    exit 1
fi

# Download and patch pypy.
if [ ! -d $PYPY_DIR ]; then
    if [ ! -f  $PYPY_FILE ]; then
        rm -rf pypy*
        wget https://bitbucket.org/pypy/pypy/downloads/$PYPY_FILE
    fi
    tar jxf $PYPY_FILE
    
    pushd $PYPY_DIR/lib-python/2.7
    
    patch -p4 < $PYPY_GZIP_PATCH
    if [ $? -ne 0 ]; then
        echo "Applying GZipFile fix for PyPy 1.9 failed."
        exit 1
    fi
    
    patch -p4 < $PYPY_URLLIB2_PATCH
    if [ $? -ne 0 ]; then
        echo "Applying urllib2 update from Python 2.7.3 for PyPy 1.9 failed."
        exit 1
    fi
    
    cp $PYPY_PSYCOPG_FILE .

    popd
fi

# Setup the virtual environment with pypy.
if [ ! -d $ENVDIR ]; then
    echo "Preparing virtualenv environment in $ENVDIR directory"
    virtualenv -p $PYPY_DIR/bin/pypy --prompt=\($BASEPATH-pypy\) $ENVDIR
fi

echo 'Installing required packages'
# Install Django first because django-countries requires Django to be fully
# installed before it will install.
DJANGO=`grep "Django==" requirements.txt`
$ENVDIR/bin/pip install $DJANGO
if [ $? -ne 0 ]; then
    echo "Error installing $DJANGO."
    exit 1
fi
if $ENVDIR/bin/pip install -r requirements.txt; then
    echo 'That went alright, continue'
else
    echo 'Error installing dependencies, breaking off'
    exit 1
fi

LOCAL_SETTINGS=$SETTINGS_DIR/local.py
LOCAL_SETTINGS_EXAMPLE=$SETTINGS_DIR/local.py.example
if [ ! -f $LOCAL_SETTINGS ]; then
    echo "No local settings file found, copying from $LOCAL_SETTINGS_EXAMPLE"
    cp -v $LOCAL_SETTINGS_EXAMPLE $LOCAL_SETTINGS
fi

SECRETS_FILE=$SETTINGS_DIR/secrets.py
SECRETS_FILE_EXAMPLE=$SETTINGS_DIR/secrets.py.example
if [ ! -f $SECRETS_FILE ]; then
    echo
    echo "No secrets file found, copying from $SECRETS_FILE_EXAMPLE"
    cp -v $SECRETS_FILE_EXAMPLE $SECRETS_FILE

    echo "Generating secret key"
    # Ref: https://build.opensuse.org/package/view_file?file=fix-initscript.dif&package=cobbler&project=systemsmanagement
    RAND_SECRET=$(openssl rand -base64 40 | sed 's/\//\\\//g')

    if [ $RAND_SECRET  ]; then
        # Update SECRET_KEY
        sed -i -e "s/^SECRET_KEY.*/SECRET_KEY = \'$RAND_SECRET\'/" $SECRETS_FILE
    else
        echo 'Error generating secret key, breaking off.'

        # Cleanup after ourselves
        rm -f $SECRETS_FILE
        exit 1
    fi
fi

echo "Please configure your local database in $SECRETS_FILE and run './manage.py syncdb --migrate to get you started.'"
