from codecs import open
from setuptools import setup

with open('README.rst', encoding='utf-8') as readme:
    long_description = readme.read()

setup(
    name='c_api_extract',
    description='Automatic extraction of C APIs from header files using libclang',
    long_description=long_description,

    url='https://github.com/gilzoide/c_api_extract-py',
    author='gilzoide',
    author_email='gilzoide@gmail.com',
    project_urls={
        'Source': 'https://github.com/gilzoide/c_api_extract-py',
        'Tracker': 'https://github.com/gilzoide/c_api_extract-py/issues',
    },

    license='Unlicense',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: Public Domain',
        'Programming Language :: Python :: 3',
        'Topic :: Software Development :: Compilers',
    ],
    keywords='c header clang',
    install_requires=['clang', 'docopt'],

    py_modules=['c_api_extract'],
    entry_points={
        'console_scripts': [
            'c_api_extract = c_api_extract:main',
        ]
    },
)
