import functools
import glob
import os.path as osp

import attr
import numpy as np

import datatools.rays as rays
import otils as ot

npa = np.array  # pylint: disable=invalid-name

TYPES = [
    ('Car', 1),
    ('Van', 1),
    ('Truck', 1),
    ('Pedestrian', 2),
    ('Person_sitting', 2),
    ('Cyclist', 2),
    ('Tram', 3),
    ('Misc', 3),
    ('DontCare', 3),
]
LAB_MAP = {t.lower(): i for t, i in TYPES}


@attr.s
class Label:
    typ = attr.ib()
    truncated = attr.ib()
    occluded = attr.ib()
    alpha = attr.ib()
    bboxl = attr.ib()
    bboxt = attr.ib()
    bboxr = attr.ib()
    bboxb = attr.ib()
    height = attr.ib()
    width = attr.ib()
    length = attr.ib()
    locx = attr.ib()
    locy = attr.ib()
    locz = attr.ib()
    roty = attr.ib()


def get_label_inds(pcl, label):
    center = np.array([label.locx, label.locy, label.locz])
    rpcl = ot.visual.rot_mat(npa([0, label.roty, 0]), rads=True).T @ (pcl - center[:, None])
    hbounds = [-label.height, 0]
    lbounds = [-label.length / 2, label.length / 2]
    wbounds = [-label.width / 2, label.width / 2]
    ind = (lbounds[0] <= rpcl[0, :]) & (rpcl[0, :] <= lbounds[1])
    ind &= (hbounds[0] <= rpcl[1, :]) & (rpcl[1, :] <= hbounds[1])
    ind &= (wbounds[0] <= rpcl[2, :]) & (rpcl[2, :] <= wbounds[1])
    return ind


def calib_loader(fname):
    with open(fname, 'rt') as f:
        result = {}
        for line in f:
            data = line.strip().split()
            if not data:
                continue
            key = data[0][:-1]
            result[key] = np.fromiter(map(float, data[1:]), dtype='<f8')
            if key[0] == 'P':
                result[key] = result[key].reshape((3, 4))
            if key[0] == 'R':
                tmp = result[key]
                result[key] = np.eye(4)
                result[key][:3, :3] = tmp.reshape((3, 3))
            if key[0] == 'T':
                tmp = result[key]
                result[key] = np.eye(4)
                result[key][:3, :] = tmp.reshape((3, 4))
    return result


def velo_loader(fname):
    return np.fromfile(fname, dtype='<f4').astype('<f8').reshape((-1, 4)).T


def label_loader(fname):
    with open(fname, 'rt') as f:
        result = []
        for line in f:
            data = line.strip().split()
            if LAB_MAP[data[0].lower()] == max(LAB_MAP.values()):
                continue
            result.append(Label(LAB_MAP[data[0].lower()], *map(float, data[1:])))
    return result


def label_semkitti_loader(fname):
    return np.fromfile(fname, dtype='u4') & 0xFFFF


class KittiDataset(ot.dataset.Dataset):
    def __init__(self, base_dir, odo_dataset=False, have_labels=True):
        num_files = ot.dataset.NumFiles(num_files=len(glob.glob(osp.join(base_dir, 'image_2', '*.png'))))
        kwargs = {'width': 6, 'odo_dataset': odo_dataset, 'have_labels': have_labels}
        super().__init__(base_dir, num_files, KittiEntry, entry_kwargs=kwargs)


class KittiEntry(ot.dataset.DatasetEntry):
    BINS = np.array([0.03577229, 0.1232794, 0.20273558, 0.24916231, 0.27905208, 0.2998364, 0.32104259, 0.34792211, 0.3898593, 0.70251575])
    EDGES = np.array([0.07952585, 0.16300749, 0.22594894, 0.2641072, 0.28944424, 0.31043949, 0.33448235, 0.3688907, 0.54618753])

    def __init__(self, parent, data_dir, data_id, width, autosave=True, odo_dataset=False, have_labels=True):
        super().__init__(parent, data_dir, data_id, width, autosave)
        self.odo_dataset = odo_dataset
        self.have_labels = have_labels
        self.calib_mat = self.calib_global['Tr'] if self.odo_dataset else self.calib['R0_rect'] @ self.calib['Tr_velo_to_cam']
        self.correct_calib = self.calib_global if self.odo_dataset else self.calib
        self.correct_label_velo = None if not self.have_labels else (self.label_semkitti if self.odo_dataset else self.label_velo)

    def _color_pcl_create(self):
        pcl = np.concatenate((self.velo, self.correct_label_velo.reshape((1, -1)), self.color_velo), axis=0)
        return pcl[:, pcl[-1, :] > 0]

    def _label_objects_create(self):
        pcl_rect = ot.visual.fromhomo(self.calib_mat @ ot.visual.tohomo(self.velo[:3, :]))
        result = {}
        for i, label in enumerate(self.label):
            inds = get_label_inds(pcl_rect, label)
            name = f'{label.type}_{i:02d}'
            result[name] = np.concatenate((self.velo[:, inds], self.color_velo[:, inds]), axis=0)
            if result[name].shape[1] <= 1:
                del result[name]
        return result

    def _grid_create(self, params, shift=None):
        inten = self.velo[-1]
        bins = np.searchsorted(self.EDGES, inten)
        dist = inten - self.BINS[bins]
        if self.have_labels:
            pcl = np.concatenate((self.velo, bins[None, ...], dist[None, ...], self.correct_label_velo[None, ...], self.color_velo), axis=0)
        else:
            pcl = np.concatenate((self.velo, bins[None, ...], dist[None, ...], self.color_velo), axis=0)
        return params.pcl2grid(pcl, camera_center=shift)

    def _lidar_pcl_create(self, name, params, shift=None):
        lidar_type = name.split('_')[0]
        grid = getattr(self, lidar_type + '_grid')
        return params.grid2pcl(grid, camera_center=shift)

    def _color_velo_create(self):
        pcl_rect = self.calib_mat @ ot.visual.tohomo(self.velo[:3, :])
        pcl2 = self.correct_calib['P2'] @ pcl_rect
        pcl3 = self.correct_calib['P3'] @ pcl_rect
        where2 = pcl2[-1, :] > 0
        where3 = pcl3[-1, :] > 0
        pcl2 = ot.visual.fromhomo(pcl2)
        pcl3 = ot.visual.fromhomo(pcl3)
        where2 &= (pcl2[0, :] >= 0) & (pcl2[1, :] >= 0) & (pcl2[0, :] < self.img2.shape[1]) & (pcl2[1, :] < self.img2.shape[0])
        where3 &= (pcl3[0, :] >= 0) & (pcl3[1, :] >= 0) & (pcl3[0, :] < self.img3.shape[1]) & (pcl3[1, :] < self.img3.shape[0])

        result = np.zeros(self.velo.shape)
        result[:3, where2] += self.img2[pcl2[1, where2].astype(np.int), pcl2[0, where2].astype(np.int), :].T
        result[3, where2] += 1
        result[:3, where3] += self.img3[pcl3[1, where3].astype(np.int), pcl3[0, where3].astype(np.int), :].T
        result[3, where3] += 1
        result = ot.visual.fromhomo(result, return_all_dims=True)
        return result

    def _label_velo_create(self):
        pcl_rect = ot.visual.fromhomo(self.calib_mat @ ot.visual.tohomo(self.velo[:3, :]))
        result = np.zeros((pcl_rect.shape[1],))
        for label in self.label:
            result[get_label_inds(pcl_rect, label)] = label.type
        return result

    def _color_pcl_gs_create(self):
        pcl = npa(self.color_pcl)
        pcl[3] = ot.visual.rgb2gs(pcl[5:8])
        return pcl

    _velo_grid_create = functools.partial(_grid_create, params=rays.velodyne_params)
    _scala_grid_create = functools.partial(_grid_create, params=rays.scala_params, shift=np.array([2.0, 0, -2]))
    _velo_pcl_create = functools.partial(_lidar_pcl_create, params=rays.velodyne_params)
    _scala_pcl_create = functools.partial(_lidar_pcl_create, params=rays.scala_params, shift=np.array([2.0, 0, -2]))

    label = ot.dataset.DataAttrib('{data_id:0{width}d}.txt', label_loader, 'label_2', deletable=False)
    label_semkitti = ot.dataset.DataAttrib('{data_id:0{width}d}.label', label_semkitti_loader, 'labels', deletable=False)
    img2 = ot.dataset.DataAttrib('{data_id:0{width}d}.png', ot.io.img_load, 'image_2', deletable=False)
    img3 = ot.dataset.DataAttrib('{data_id:0{width}d}.png', ot.io.img_load, 'image_3', deletable=False)
    calib = ot.dataset.DataAttrib('{data_id:0{width}d}.txt', calib_loader, 'calib', deletable=False, wfable=False)
    calib_global = ot.dataset.DataAttrib('calib.txt', calib_loader, '.', deletable=False, wfable=False)
    velo = ot.dataset.DataAttrib('{data_id:0{width}d}.bin', velo_loader, 'velodyne', deletable=False)
    color_velo = ot.dataset.DataAttrib('{data_id:0{width}d}.npy', np.load, 'color_velo', _color_velo_create, np.save)
    label_velo = ot.dataset.DataAttrib('{data_id:0{width}d}.npy', np.load, 'label_velo', _label_velo_create, np.save)
    color_pcl = ot.dataset.DataAttrib('{data_id:0{width}d}.npy', np.load, 'color_pcl', _color_pcl_create, np.save)
    color_pcl_gs_inten = ot.dataset.DataAttrib('{data_id:0{width}d}.npy', np.load, 'color_pcl_gs', _color_pcl_gs_create, np.save)
    label_objects = ot.dataset.DataAttrib(
        '{data_id:0{width}d}.npz', lambda fname: dict(np.load(fname)), 'label_objects', _label_objects_create, ot.io.np_savez
    )
    velodyne_grid = ot.dataset.DataAttrib('{data_id:0{width}d}.npy', np.load, ('pseudo-velodyne', 'grid'), _velo_grid_create, np.save)
    scala_grid = ot.dataset.DataAttrib('{data_id:0{width}d}.npy', np.load, ('pseudo-scala', 'grid'), _scala_grid_create, np.save)
    velodyne_pcl = ot.dataset.DataAttrib(
        '{data_id:0{width}d}.npy', np.load, ('pseudo-velodyne', 'pcl'), _velo_pcl_create, np.save, ['name']
    )
    scala_pcl = ot.dataset.DataAttrib('{data_id:0{width}d}.npy', np.load, ('pseudo-scala', 'pcl'), _scala_pcl_create, np.save, ['name'])
