import enum
import functools
import glob
import itertools as it
import os.path as osp
import warnings

import attr
import numpy as np
from PIL import Image, ImageDraw

import datatools.rays as rays
import otils as ot

npa = np.array  # pylint: disable=invalid-name


class CarClass(enum.Enum):
    def _generate_next_value_(name, _, __, last_values):  # pylint: disable=no-self-argument
        prev_val, prev_id = last_values[-1]
        return (prev_val + 1, prev_id)

    Unknown = (1, 1)
    Compacts = (8, 2)
    Sedans = enum.auto()  # 9
    SUVs = enum.auto()  # 10
    Coupes = enum.auto()  # 11
    Muscle = enum.auto()  # 12
    SportsClassics = enum.auto()  # 13
    Sports = enum.auto()  # 14
    Super = enum.auto()  # 15
    Motorcycles = enum.auto()  # 16
    OffRoad = enum.auto()  # 17
    Industrial = enum.auto()  # 18
    Utility = enum.auto()  # 19
    Vans = enum.auto()  # 20
    Cycles = enum.auto()  # 21
    Boats = enum.auto()  # 22
    Helicopters = enum.auto()  # 23
    Planes = enum.auto()  # 24
    Service = enum.auto()  # 25
    Emergency = enum.auto()  # 26
    Military = enum.auto()  # 27
    Commercial = enum.auto()  # 28
    Trains = enum.auto()  # 29


ORIG2EGO = np.array([[0, 0, -1], [-1, 0, 0], [0, 1, 0]])
WORLD2EGO_POS = np.array([[0, 1, 0], [1, 0, 0], [0, 0, 1]])


# ORIG EGO COORDS
# X -> RIGHT
# Y -> UP
# Z -> BACK

# EGO PCL COORDS ("regular" coords for pcl)
# X -> FRONT
# Y -> LEFT
# Z -> UP

# WORLD COORDS:
# X -> RIGHT
# Y -> FRONT
# Z -> UP


def _depth_loader(filename):
    return ot.io.img_load(filename, '<u2', div=float(np.iinfo('<u2').max))


def _stencil_loader(filename):
    return ot.io.img_load(filename, 'u1', 'u1', 1) & 7


@attr.s
class GTAEntry(ot.dataset.DatasetEntry):
    STENCIL_COLORS = npa(
        [
            (230, 25, 75, 50),
            (60, 180, 75, 50),
            (255, 225, 25, 50),
            (0, 130, 200, 50),
            (245, 130, 48, 50),
            (145, 30, 180, 50),
            (70, 240, 240, 50),
            (240, 50, 230, 50),
        ],
        dtype='u1',
    )

    bbox = attr.ib(default=(130, 130, 130))

    def _create_overlay(self, what, colors, over='rgb'):
        over = getattr(self, over)
        what = getattr(self, what)
        overlay = np.zeros(list(over.shape[0:2]) + [4], dtype='u1')
        for i, color in enumerate(colors):
            overlay[what == i] = color.T
        return (ot.visual.blend_img(over, overlay / 255.0) * 255).astype('u1')

    def _create_bbox_data(self):
        proj = npa(self.meta['proj_matrix'])
        view = npa(self.meta['view_matrix'])
        entities = self.meta['entities']
        height = self.meta['height']
        width = self.meta['width']
        bbox3d = []
        colors = []
        bbox2d = []
        world = []
        mats = []
        clazz = []
        for entity in entities:
            pts = list(it.product(*npa(entity['model_sizes']).reshape((3, 2)).tolist()))
            world_pts = ot.visual.rot_mat(npa(entity['rot'])) @ npa(pts).T + npa(entity['pos'])[:, None]
            ego_pts = ot.visual.fromhomo(view @ ot.visual.tohomo(world_pts))
            if self.bbox is not None:
                ind = (
                    (np.abs(ego_pts[0, :]) < self.bbox[0]) & (np.abs(ego_pts[1, :]) < self.bbox[1]) & (np.abs(ego_pts[2, :]) < self.bbox[2])
                )
                if not np.all(ind):
                    continue
            im_pts = ot.visual.fromhomo(proj @ ot.visual.tohomo(ego_pts))
            if np.all(im_pts[2] >= 0.15):
                continue
            if np.all((im_pts[0] < -1) | (im_pts[0] > 1) | (im_pts[1] < -1) | (im_pts[1] > 1)):
                continue
            nworld = ot.visual.tohomo(world_pts)
            mat = np.concatenate((nworld[:, [1, 2, 4]] - nworld[:, [0]], nworld[:, [0]]), 1)
            mats.append(np.linalg.inv(mat))
            clazz_val = CarClass.__members__.get(entity['class'], None)
            if clazz_val is None:
                value = (2, 2)
            else:
                value = clazz_val.value
            clazz.append(value)
            im_pts = im_pts[:2]
            im_pts[0] = (im_pts[0] + 1) * (width / 2)
            im_pts[1] = (im_pts[1] - 1) * (-height / 2)
            bbox3d.append(im_pts)
            colors.append((255, 0, 0, 255) if entity['type'] == 'person' else (0, 255, 0, 255))
            bbox2d.append(npa(list(it.product(*np.stack((im_pts.min(1), im_pts.max(1)), -1)))).T)
            world.append(world_pts)
        return {
            'bbox3d': npa(bbox3d),
            'bbox2d': npa(bbox2d),
            'colors': npa(colors),
            'world': npa(world),
            'mats': npa(mats),
            'clazz': npa(clazz),
        }

    def _draw_bbox(self, bbox_key, connection):
        bbox_data = self.bbox_data
        img = Image.fromarray((self.rgb * 255.0).astype('u1'))
        draw = ImageDraw.Draw(img)
        for bbox, color in zip(bbox_data[bbox_key], bbox_data['colors']):
            ot.visual.draw_bbox(draw, bbox.T.tolist(), color, connection)
        return npa(img)

    def reclazz(self, coords, stencil):
        bbox_data = self.bbox_data
        changes = set((old for new, old in bbox_data['clazz']))
        change_mask = functools.reduce(lambda x, y: x | y, ((stencil == c) for c in changes), np.zeros(stencil.shape, dtype=bool))
        tmp_coords = coords[:, change_mask]
        tmp_stencil = stencil[change_mask]
        for (new_clazz, old_clazz), mat in zip(bbox_data['clazz'], bbox_data['mats']):
            npts = ot.visual.fromhomo(mat @ tmp_coords)
            where = (
                (npts[0] >= 0) & (npts[0] <= 1) & (npts[1] >= 0) & (npts[1] <= 1) & (npts[2] >= 0) & (npts[2] <= 1) & (tmp_stencil == old_clazz)
            )
            tmp_stencil[where] = new_clazz
        stencil[change_mask] = tmp_stencil
        return stencil

    def _create_pcl(self):
        proji = np.linalg.inv(npa(self.meta['proj_matrix']))
        viewi = np.linalg.inv(npa(self.meta['view_matrix']))
        height, width = self.depth.shape
        y, x = np.where(self.depth > 0.0)
        y_data = (-2 / height) * y + 1  # gta math
        x_data = (2 / width) * x - 1  # gta math

        ego_points = ot.visual.fromhomo(
            proji @ ot.visual.tohomo(np.concatenate((x_data[None, :], y_data[None, :], self.depth[y, x][None, :]), axis=0))
        )

        if self.bbox is not None:
            ind = (
                (np.abs(ego_points[0, :]) < self.bbox[0])
                & (np.abs(ego_points[1, :]) < self.bbox[1])
                & (np.abs(ego_points[2, :]) < self.bbox[2])
            )
        else:
            ind = np.ones((ego_points.shape[1],), dtype=np.bool)
        coords = viewi @ ot.visual.tohomo(ego_points[:, ind])
        clazz = self.reclazz(coords, self.stencil[y[ind], x[ind]])
        return np.concatenate((ot.visual.fromhomo(coords), clazz[None, ...], self.rgb[y[ind], x[ind]].T, np.ones((1, np.sum(ind)))), axis=0)

    def _create_ego_pcl(self):
        pcl = self.pcl
        pcl, features = pcl[:3], pcl[3:]
        view = npa(self.meta['view_matrix'])
        relative_rot = ot.visual.rot_mat(np.zeros(3), self.meta['camera_relative_rotation'])
        npcl = (
            relative_rot.T @ ORIG2EGO @ ot.visual.fromhomo(view @ ot.visual.tohomo(pcl))
            + (WORLD2EGO_POS @ npa(self.meta['camera_relative_position']))[:, None]
        )
        return np.concatenate((npcl, features), axis=0)

    def _create_lidar_grid(self, params, allowance, start_id, stride, together):
        if (self.data_id - start_id) % stride != 0:
            warnings.warn('We should not get here!')
            return None
        pcl = np.concatenate(self.parent.ego_pcl[self.data_id : (self.data_id + together)], axis=1)
        return params.pcl2grid(pcl, allowance, camera_center=WORLD2EGO_POS @ npa(self.parent.meta[start_id]['camera_relative_position']))

    def _create_lidar_pcl(self, params, name, start_id, stride, world=False):
        if (self.data_id - start_id) % stride != 0:
            warnings.warn('We should not get here!')
            return None
        lidar_type = name.split('_')[0]
        grid = getattr(self, lidar_type + '_grid')
        pos = WORLD2EGO_POS @ npa(self.parent.meta[start_id]['camera_relative_position'])
        ego_pcl = params.grid2pcl(grid, camera_center=pos)
        if not world:
            return ego_pcl
        ego_pcl, features = ego_pcl[:3], ego_pcl[3:]
        relative_rot = ot.visual.rot_mat(np.zeros(3), self.parent.meta[start_id]['camera_relative_rotation'])
        view = npa(self.parent.meta[start_id]['view_matrix'])
        npcl = ot.visual.fromhomo(np.linalg.inv(view) @ ot.visual.tohomo(ORIG2EGO.T @ relative_rot @ (ego_pcl - pos)))
        return np.concatenate((npcl, features), axis=0)

    _draw_bbox2d = functools.partial(_draw_bbox, bbox_key='bbox2d', connection=ot.visual.BBOX_CONNS['2D'])
    _draw_bbox3d = functools.partial(_draw_bbox, bbox_key='bbox3d', connection=ot.visual.BBOX_CONNS['3D'])
    _draw_overlay_stencil = functools.partial(_create_overlay, what='stencil', colors=STENCIL_COLORS)
    _create_velo_grid = functools.partial(_create_lidar_grid, params=rays.velodyne_params, allowance=0.2)
    _create_velo_pcl = functools.partial(_create_lidar_pcl, params=rays.velodyne_params)
    _create_velo_pcl_world = functools.partial(_create_lidar_pcl, params=rays.velodyne_params, world=True)
    _create_scala_grid = functools.partial(_create_lidar_grid, params=rays.scala_params, allowance=0.2)
    _create_scala_pcl = functools.partial(_create_lidar_pcl, params=rays.scala_params)
    _create_scala_pcl_world = functools.partial(_create_lidar_pcl, params=rays.scala_params, world=True)
    rgb = ot.dataset.DataAttrib('{data_id:0{width}d}.png', ot.io.img_load, ('orig', 'orig-rgb'), deletable=False)
    depth = ot.dataset.DataAttrib('{data_id:0{width}d}.png', _depth_loader, ('orig', 'orig-depth'), deletable=False)
    stencil = ot.dataset.DataAttrib('{data_id:0{width}d}.png', _stencil_loader, ('orig', 'orig-stencil'), deletable=False)
    meta = ot.dataset.DataAttrib('{data_id:0{width}d}.json', ot.io.read_json, ('orig', 'orig-json'), wfable=False, deletable=False)
    pcl = ot.dataset.DataAttrib('{data_id:0{width}d}.npy', ot.io.np_load, ('processed', 'pcl'), _create_pcl, np.save)
    ego_pcl = ot.dataset.DataAttrib('{data_id:0{width}d}.npy', ot.io.np_load, ('processed', 'ego_pcl'), _create_ego_pcl, np.save)
    overlay_stencil = ot.dataset.DataAttrib(
        '{data_id:0{width}d}.png', ot.io.img_load, ('processed', 'overlays_stencil'), _draw_overlay_stencil, ot.io.img_save
    )
    bbox_data = ot.dataset.DataAttrib(
        '{data_id:0{width}d}.npz',
        lambda fname: dict(np.load(fname)),
        ('processed', 'bbox_data'),
        _create_bbox_data,
        ot.io.np_savez,
        wfable=False,
    )
    bbox3d = ot.dataset.DataAttrib('{data_id:0{width}d}.png', ot.io.img_load, ('processed', 'bbox3d'), _draw_bbox3d, ot.io.img_save)
    bbox2d = ot.dataset.DataAttrib('{data_id:0{width}d}.png', ot.io.img_load, ('processed', 'bbox2d'), _draw_bbox2d, ot.io.img_save)


class GTADataset(ot.dataset.Dataset):
    def __init__(self, base_dir, bbox=(130, 130, 130), velodyne=True, scala=True, dash=True, base=GTAEntry, **kwargs):
        num_files = ot.dataset.NumFiles(num_files=len(glob.glob(osp.join(base_dir, 'orig', 'orig-json', '*.json'))))
        kwargs['bbox'] = bbox
        populace_dict = dict(base.__dict__)
        stride = int(velodyne) * 4 + int(scala) * 2 + int(dash)
        scala_start = int(velodyne) * 4
        if velodyne:
            populace_dict['velodyne_grid'] = ot.dataset.DataAttrib(
                '{data_id:0{width}d}.npy',
                ot.io.np_load,
                ('processed', 'velodyne', 'grid'),
                base._create_velo_grid,  # pylint: disable=protected-access
                np.save,
                ['start_id', 'stride', 'together'],
                0,
                stride,
                4,
            )
            populace_dict['velodyne_pcl'] = ot.dataset.DataAttrib(
                '{data_id:0{width}d}.npy',
                ot.io.np_load,
                ('processed', 'velodyne', 'ego_pcl'),
                base._create_velo_pcl,  # pylint: disable=protected-access
                np.save,
                ['name', 'start_id', 'stride'],
                0,
                stride,
                4,
            )
            populace_dict['velodyne_world_pcl'] = ot.dataset.DataAttrib(
                '{data_id:0{width}d}.npy',
                ot.io.np_load,
                ('processed', 'velodyne', 'world_pcl'),
                base._create_velo_pcl_world,  # pylint: disable=protected-access
                np.save,
                ['name', 'start_id', 'stride'],
                0,
                stride,
                4,
            )
        if scala:
            populace_dict['scala_grid'] = ot.dataset.DataAttrib(
                '{data_id:0{width}d}.npy',
                ot.io.np_load,
                ('processed', 'scala', 'grid'),
                base._create_scala_grid,  # pylint: disable=protected-access
                np.save,
                ['start_id', 'stride', 'together'],
                scala_start,
                stride,
                2,
            )
            populace_dict['scala_pcl'] = ot.dataset.DataAttrib(
                '{data_id:0{width}d}.npy',
                ot.io.np_load,
                ('processed', 'scala', 'ego_pcl'),
                base._create_scala_pcl,  # pylint: disable=protected-access
                np.save,
                ['name', 'start_id', 'stride'],
                scala_start,
                stride,
                2,
            )
            populace_dict['scala_pcl_world'] = ot.dataset.DataAttrib(
                '{data_id:0{width}d}.npy',
                ot.io.np_load,
                ('processed', 'scala', 'world_pcl'),
                base._create_scala_pcl_world,  # pylint: disable=protected-access
                np.save,
                ['name', 'start_id', 'stride'],
                scala_start,
                stride,
                2,
            )
        new_name = base.__name__ + '_computed'
        comp_class = type(new_name, base.__bases__, populace_dict)
        globals()[new_name] = comp_class  # ugly fuckery because of pickles
        super().__init__(base_dir, num_files, comp_class, entry_kwargs=kwargs)
