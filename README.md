# Learning  to  predict  Lidar  intensities
## Dataset for download
## Grid version
- [geometry](https://login.rci.cvut.cz/data/lidar_intensity/grid/geometry.tar.gz)
- [intensity](https://login.rci.cvut.cz/data/lidar_intensity/grid/intensity.tar.gz)
- [labels](https://login.rci.cvut.cz/data/lidar_intensity/grid/labels.tar.gz)
- [color](https://login.rci.cvut.cz/data/lidar_intensity/grid/color.tar.gz)
- [mask](https://login.rci.cvut.cz/data/lidar_intensity/grid/mask.tar.gz)


## Point cloud version
- [geometry](https://login.rci.cvut.cz/data/lidar_intensity/pcl/geometry.tar.gz)
- [intensity](https://login.rci.cvut.cz/data/lidar_intensity/pcl/intensity.tar.gz)
- [labels](https://login.rci.cvut.cz/data/lidar_intensity/pcl/labels.tar.gz)
- [color](https://login.rci.cvut.cz/data/lidar_intensity/pcl/color.tar.gz)
- [mask](https://login.rci.cvut.cz/data/lidar_intensity/pcl/mask.tar.gz)

## How to run everything

GTA plugins are available in directory GTA. Please follow the instructions from the original [GTAVisionExport](https://github.com/umautobots/GTAVisionExport) repository to make it work.

Some notable changes from the original repository:

- 4 cameras which switch themselves sitting atop a car to simulate lidar, each with 65 VFOV (~91 HFOV)
- It is made substantially more lightweight in order to keep only necessary parts.

First go through GTA directory to setup the GTA plugins and collect dataset

Then go through python directory, to compute velodyne-like points.

In order to predict intensity, use `python/model_eval.py`, the best model checkpoint can be downloaded from [here](https://login.rci.cvut.cz/data/lidar_intensity/model/best.tar)

### Configs

Folder configs contains configs for starting either `python/model_eval.py` or `python/model_train.py`. Each config in the toplevel `configs` directory is a list of configs from includes, which are merged together. The order is important, if there are two same keys in different included files, the one that was included later is kept.

You will probably want to change `configs/includes/{gta,kitti}data/basedata.yml` and `config/includes/{gta,kitti}data/segment_data.yml`, which contains paths for data.

Configs `configs/includes/{reflect,segment}_configs/model*.yml` contain directories, where checkpoints are stored. You probably want to change that too.
