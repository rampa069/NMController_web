#! /bin/sh
echo 'removing dist folder...'
rm -rf build dist
echo 'dist folder removed, packing app for mac'
python setup.py py2app