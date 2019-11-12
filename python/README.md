# Python Utils for Extracting lidar intensities

0. Portion of the code is in Cython. There is an attached Makefile to compile it, however it is not necessary to use the Makefile, simple `python3 setup.py build_ext --inplace` works (i.e. it should work on windows too)

1. First, run `prepare_dataset.py` in order to extract a dataset info from PostgreSQL database and convert data to friendlier-than-tiff format. It uses `gta.yml` config file, read help of the utility for detailed usage

2. Then run `create_velodynes.py` in order to create velodyne-like data.

Scripts `model_eval.py` and `model_run.py` are helpers to run PyTorch models specified by configs