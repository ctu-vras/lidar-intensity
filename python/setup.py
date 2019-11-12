from Cython.Build import cythonize
from setuptools import setup
from setuptools.extension import Extension

extensions = [  # pylint: disable=invalid-name
    Extension(
        "datatools.rays",
        ["datatools/rays.pyx"],
        libraries=['m'],
        extra_compile_args=['-fopenmp', '-O2', '-march=native'],
        extra_link_args=['-fopenmp', '-O2', '-march=native'],
    )
]

setup(name="rays", ext_modules=cythonize(extensions))
