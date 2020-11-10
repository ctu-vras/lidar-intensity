# cython: language_level=3,boundscheck=False,language=c++

import numpy as np
cimport numpy as cnp
from libc cimport math
from cython.parallel import prange, parallel
from cython cimport floating

INT = '<i8'
DOUBLE = '<f8'

ctypedef cnp.float64_t double_t
ctypedef cnp.int64_t long_t

na = np.asarray

cdef class Angles:
    cdef:
        readonly double_t[:] starts, diffs, angles
        readonly long_t parts, total
        readonly long_t[:] lengths
    
    def __cinit__(self, double_t[:] angles):
        self.total = len(angles)
        self.angles = angles
        self.create_diffs(angles)
        self.parts = len(self.lengths)
    
    def __reduce__(self):
        return Angles, (self.angles.base,)
    
    cdef create_diffs(self, double_t[:] data):
        cdef:
            list starts = [], diffs = [], lengths = []
            long_t i = 0, last_start = 0
            double_t last_diff = 0
        for i in range(len(data) - 1):
            if not np.isclose(last_diff, data[i+1] - data[i]):
                if i - last_start:
                    starts.append(data[last_start])
                    diffs.append(last_diff)
                    lengths.append(i - last_start + 1)
                last_diff = data[i+1] - data[i]
                if i:
                    last_start = i + 1
                else:
                    last_start = i
        i += 1
        starts.append(data[last_start])
        diffs.append(last_diff)
        lengths.append(i - last_start + 1)
        self.starts = np.array(starts, dtype=DOUBLE)
        self.diffs = np.array(diffs, dtype=DOUBLE)
        self.lengths = np.array(lengths, dtype=INT)
    
    cdef (double_t, long_t) find_value(self, double_t value) nogil:
        cdef:
            long_t i, rnd, acc_length = 0
            double_t val, minval, maxval
            bint swapped
        for i in range(self.parts):
            val = (value - self.starts[i]) / self.diffs[i]
            rnd = <long_t>math.round(val)
            if val <= self.lengths[i] - 1 and rnd >= 0:
                return val + acc_length, rnd + acc_length
            if val < 0:
                return 0, -1
            if i < self.parts - 1:
                minval = (self.lengths[i] - 1) * self.diffs[i] + self.starts[i]
                maxval = self.starts[i + 1]
                swapped = False
                if minval > maxval:
                    minval, maxval = maxval, minval
                    swapped = True
                val = (value - minval) / (maxval - minval)                
                if val <= 1 and val >= 0:
                    if swapped:
                        val = 1 - val
                    val = val + acc_length + self.lengths[i] - 1
                    return val, <long_t>math.round(val)
            elif rnd == self.lengths[i] - 1:
                return val + acc_length, rnd + acc_length
            acc_length += self.lengths[i]
        return 0, -1


cdef class LiDARParams:
    cdef:
        readonly double_t minimal_ray_dist, maximal_ray_dist, valid_point
        readonly Angles vertical, horizontal
    
    def __cinit__(self,
                  double_t minimal_ray_dist,
                  double_t maximal_ray_dist,
                  double_t[:] vertical_angles,
                  double_t[:] horizontal_angles,
                  double_t valid_point=0.5):
        self.minimal_ray_dist = minimal_ray_dist
        self.maximal_ray_dist = maximal_ray_dist
        self.valid_point = valid_point
        self.vertical = Angles(vertical_angles)
        self.horizontal = Angles(horizontal_angles)

    
    def __reduce__(self):
        return LiDARParams, (self.minimal_ray_dist, self.maximal_ray_dist, self.vertical.angles.base, self.horizontal.angles.base, self.valid_point)
    
    cpdef pcl2grid(self,
                   floating[:, :] pcl,
                   floating allowance=0.5,
                   floating[:] camera_center=None,
                   floating[:, :] camera_rotation=None):
        '''
        pcl - [m x n] array, m>= 3, first 3 channels correspond to xyz
        allowance - what maximal value of displacement to allow. 0.5 is the maximal possible value
        camera_center - [3] vector
        camera_rotation - [3 x 3] rotation matrix.

        The raycasting will be done on R^T ([XYZ] - camera_center)

        Result will have [a x b x c] dimensions, where a = vertical resolution, b = horizontal resolution, c = m+2. First channel is distance to the point, last channel is a binary mask whether any point is in the spot, and everything in between is copied from corresponding point in pcl (where xyz is transformed)
        '''
        cdef:
            double_t[:, :, :] result
        dtype = na(pcl).dtype
        if camera_center is None:
            camera_center = np.zeros((3, ), dtype=dtype)
        if camera_rotation is None:
            camera_rotation = np.eye(3, dtype=dtype)
        result = na(self._pcl2grid(na(pcl).astype(DOUBLE), allowance, na(camera_center).astype(DOUBLE), na(camera_rotation).astype(DOUBLE)))
        if floating is float:
            return result.astype(dtype)
        else:
            return result
    
    cpdef grid2pcl(self,
                   floating[:, :, :] grid,
                   floating[:] camera_center=None,
                   floating[:, :] camera_rotation=None):
        '''
        grid - expecting the result from pcl2grid
        camera_center and rotation have the same semantic
        resulting pointcloud will have xyz^* = R[XYZ] + camera_center
        '''
        cdef:
            double_t[:, :] result
        dtype = na(grid).dtype
        if camera_center is None:
            camera_center = np.zeros((3, ), dtype=dtype)
        if camera_rotation is None:
            camera_rotation = np.eye(3, dtype=dtype)
        result = na(self._grid2pcl(na(grid).astype(DOUBLE), na(camera_center).astype(DOUBLE), na(camera_rotation).astype(DOUBLE)))
        if floating is float:
            return result.astype(dtype)
        else:
            return result

    cdef double_t[:, :, :] _pcl2grid(self,
                                   double_t[:, :] pcl,
                                   double_t allowance,
                                   double_t[:] camera_center,
                                   double_t[:, :] camera_rotation):
        cdef:
            long_t num_points = pcl.shape[1], i, x_trun, y_trun, pcl_width = pcl.shape[0]
            double_t[:, :] new_pcl = na(camera_rotation).T @ (na(pcl)[:3] - na(camera_center)[:, None])
            double_t[:, :] max_val = np.empty((self.vertical.total, self.horizontal.total), dtype=DOUBLE)
            double_t[:, :, :] result = np.zeros((self.vertical.total, self.horizontal.total, pcl_width + 2), dtype=DOUBLE)
            double_t dist, yaw, pitch, x_full, y_full, err
        na(max_val).fill(allowance)
        for i in prange(num_points, nogil=True):
            dist = math.sqrt(new_pcl[0, i] * new_pcl[0, i] + new_pcl[1, i] * new_pcl[1, i] + new_pcl[2, i] * new_pcl[2, i])
            if dist < self.minimal_ray_dist or dist > self.maximal_ray_dist:
                continue
            yaw = math.atan2(new_pcl[1, i], new_pcl[0, i])  * 180 / math.M_PI + 360
            pitch = math.asin(new_pcl[2, i]/dist) * 180 / math.M_PI
            y_full, y_trun = self.horizontal.find_value(yaw)
            if y_trun == -1:
                continue
            x_full, x_trun = self.vertical.find_value(pitch)
            if x_trun == -1:
                continue
            err = (y_full - y_trun) * (y_full - y_trun) + (x_full - x_trun) * (x_full - x_trun)
            if err <= max_val[x_trun, y_trun]:
                max_val[x_trun, y_trun] = err
                result[x_trun, y_trun, 0] = dist
                result[x_trun, y_trun, 1:4] = new_pcl[:, i]
                result[x_trun, y_trun, 4:pcl_width+1] = pcl[3:, i]
                result[x_trun, y_trun, pcl_width+1] = 1
        return result
    
    cdef double_t[:, :] _grid2pcl(self,
                                double_t[:, :, :] grid,
                                double_t[:] camera_center,
                                double_t[:, :] camera_rotation):
        cdef:
            double_t [:] ray = np.array([1, 0, 0], dtype=DOUBLE)
            double_t [:, :] result, tmp
            long_t[:] x, y
            long_t valid_dim = grid.shape[2] - 1
        y, x = np.where((na(grid)[:,:,valid_dim] >= self.valid_point) & (na(grid)[:,:,0] >= self.minimal_ray_dist) & (na(grid)[:,:,0] <= self.maximal_ray_dist))
        result = np.zeros((valid_dim - 1, len(y)))
        tmp = na(grid)[y, x, 1:4].T
        na(result)[:3, :] = na(camera_rotation) @ na(tmp) + na(camera_center)[:, None]
        na(result)[3:, :] = na(grid)[y, x, 4:valid_dim].T
        return result

cdef:
    double_t[:] velodyne_vertical = np.concatenate((np.linspace(4 + (1.0 / 3), (-8 - 1.0 / 3), 40), np.linspace((-8 - 1.0 / 3 - 1.0 / 2), (-24 - 1.0 / 3), 32)))
    double_t[:] velodyne_horizontal = np.flip(np.arange(0, 360, 0.1728)) + 180

velodyne_params = LiDARParams(0.9, 131.0, velodyne_vertical, velodyne_horizontal)