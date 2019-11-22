import platform

import numpy as np
from Cython.Build import cythonize
from setuptools import setup
from setuptools.extension import Extension

if platform.system() == 'Windows':
    kwargs = {
        'extra_compile_args': ['/openmp', '/O2'],
        'extra_link_args': ['/openmp', '/O2'],
    }
else:
    kwargs = {
        'libraries': ['m'],
        'extra_compile_args': ['-fopenmp', '-O2', '-march=native'],
        'extra_link_args': ['-fopenmp', '-O2', '-march=native'],
    }

extensions = [Extension("datatools.rays", ["datatools/rays.pyx"], include_dirs=[np.get_include()], **kwargs)]  # pylint: disable=invalid-name

setup(name="rays", ext_modules=cythonize(extensions))
