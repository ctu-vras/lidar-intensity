import glob
import json
import math
import os
import re

import attr
import numpy as np
from PIL import Image

from . import gta_math, query


def img_save(data, fname):
    Image.fromarray(data).save(fname)


def json_save(data, fname):
    with open(fname, 'wt') as f:
        json.dump(data, f)


SUFFICES = {'rgb': '.tiff', 'depth': '-depth.tiff', 'stencil': '-stencil.tiff'}

OUT_DIRS = ['orig-rgb', 'orig-depth', 'orig-stencil', 'orig-json']
OUT_SUFFICES = ['.png', '.png', '.png', '.json']
OUT_ATTRS = ['rgb', 'depth', 'stencil', 'meta']
OUT_SAVERS = [img_save, img_save, img_save, json_save]

LOG_REGEX = r"""^.+[cC]omputed.+position.+:\s+(?P<comp_pos>X:-?[0-9]+(\.[0-9]+)?\ Y:-?[0-9]+(\.[0-9]+)?\ Z:-?[0-9]+(\.[0-9]+)?)$\n
^.+[nN]ew.+position.+:\s+(?P<rep_pos>X:-?[0-9]+(\.[0-9]+)?\ Y:-?[0-9]+(\.[0-9]+)?\ Z:-?[0-9]+(\.[0-9]+)?)$\n
^.+[cC]omputed.+rotation.+:\s+(?P<comp_rot>X:-?[0-9]+(\.[0-9]+)?\ Y:-?[0-9]+(\.[0-9]+)?\ Z:-?[0-9]+(\.[0-9]+)?)$\n
^.+[nN]ew.+rotation.+:\s+(?P<rep_rot>X:-?[0-9]+(\.[0-9]+)?\ Y:-?[0-9]+(\.[0-9]+)?\ Z:-?[0-9]+(\.[0-9]+)?)$\n
(^.+$\n)+? # one more line
^.+(?P<file_name>[0-9]{4}-[0-9]{2}-[0-9]{2}--[0-9]{2}-[0-9]{2}-[0-9]{2}--[0-9]{3})$"""

LOG_PATTERN = re.compile(LOG_REGEX, re.VERBOSE | re.MULTILINE)


@attr.s
class Snapshot:
    snapshot_data = attr.ib()
    img_id = attr.ib()
    rgb = attr.ib(init=False)
    depth = attr.ib(init=False)
    stencil = attr.ib(init=False)
    meta = attr.ib(init=False)

    def load_rgb(self, args):
        try:
            self.rgb = np.array(Image.open(os.path.join(args.in_dir, self.snapshot_data.imagepath + SUFFICES['rgb'])))
        except OSError as e:
            if args.verbose:
                print(f'There was something wrong with loading RGB image! The exception was {e}')
            return False
        return True

    def load_depth(self, args):
        try:
            self.depth = np.array(Image.open(os.path.join(args.in_dir, self.snapshot_data.imagepath + SUFFICES['depth'])))
            self.depth *= np.iinfo(np.uint16).max
            self.depth = self.depth.astype(np.int32)
        except OSError as e:
            if args.verbose:
                print(f'There was something wrong with loading depth image! The exception was {e}')
            return False
        return True

    def load_stencil(self, args):
        try:
            self.stencil = np.array(Image.open(os.path.join(args.in_dir, self.snapshot_data.imagepath + SUFFICES['stencil'])))
        except OSError as e:
            if args.verbose:
                print(f'There was something wrong with loading stencil image! The exception was {e}')
            return False
        return True

    def load_meta(self, args):
        log_data = args.log_data.get(self.snapshot_data.imagepath, None)
        data = self.snapshot_data._asdict()  # pylint: disable=protected-access
        if log_data is not None:
            pos_diff = np.linalg.norm(log_data['comp_pos'] - log_data['rep_pos'])
            rot_ang_diff = np.radians(log_data['comp_rot']) - np.radians(log_data['rep_rot'])
            rot_diff = np.linalg.norm(np.arctan2(np.sin(rot_ang_diff), np.cos(rot_ang_diff)))
            if pos_diff > 0.01:  # Difference largere than 1 cm
                if args.verbose:
                    print(f'Resetting position! Diff was {pos_diff}')
                    print(log_data['comp_pos'], log_data['rep_pos'])
                data['camera_pos'] = log_data['comp_pos'].tolist()
            if rot_diff > np.radians(1):  # Norm of three dirfferences of angles larger than 1 degree
                if args.verbose:
                    print(f'Resetting rotation! Diff was {np.degrees(rot_diff)}')
                    print(log_data['comp_rot'], log_data['rep_rot'])
                data['camera_rot'] = log_data['comp_rot'].tolist()
        data['view_matrix'] = gta_math.construct_view_matrix(data['camera_pos'], data['camera_rot']).tolist()
        data['proj_matrix'] = gta_math.construct_proj_matrix(data['height'], data['width'], data['camera_fov'], data['cam_near_clip']).tolist()
        args.cursor.execute(query.ENTITIES, (self.snapshot_data.snapshot_id,))
        entities = args.cursor.fetchall()
        data['entities'] = list(map(process_entity, entities))
        data['timestamp'] = data['timestamp'].strftime("%Y-%m-%d %H:%M:%S")
        data['timeofday'] = data['timeofday'].strftime("%H:%M:%S")
        self.meta = data
        return True

    def save_snapshot(self, args):
        file_base = os.path.join(args.output_dir, f'{args.current_run_id}', 'orig', '{dir_kind}', f'{self.img_id:0{args.format_width}d}' + '{suf}')
        for d, suf, att, save in zip(OUT_DIRS, OUT_SUFFICES, OUT_ATTRS, OUT_SAVERS):
            fname = file_base.format(dir_kind=d, suf=suf)
            data = getattr(self, att)
            try:
                os.makedirs(os.path.dirname(fname), exist_ok=True)
                save(data, fname)
            except OSError as e:
                if args.verbose:
                    print(f'Failed to save file {fname}! Error was: {e}')
                return False
        if args.delete_originals:
            delete_orig_files([self.snapshot_data], args)
        return True


def process_entity(entity):
    entity = entity._asdict()  # pylint: disable=protected-access
    entity['model_size'] = entity.pop('bbox3d')
    entity['bbox'] = np.array([float(i) for i in re.sub('[()]', '', entity['bbox']).split(',')]).reshape(2, 2).tolist()
    return entity


def delete_orig_files(snapshots, args):
    for snapshot in snapshots:
        args.cursor.execute(query.DELETE_SNAPSHOT, (snapshot.snapshot_id,))
        file_base = os.path.join(args.in_dir, snapshot.imagepath)
        for suffix in SUFFICES.values():
            try:
                os.remove(file_base + suffix)
            except OSError as e:
                if args.verbose:
                    print(f'Failed to remove file {file_base + suffix}! Error was: {e}')


def delete_created_files(dataitems, args):
    for dataitem in dataitems:
        file_base = os.path.join(
            args.output_dir, f'{args.current_run_id}', 'orig', '{dir_kind}', f'{dataitem.img_id:0{args.format_width}d}' + '{suf}'
        )
        for d, s in zip(OUT_DIRS, OUT_SUFFICES):
            try:
                fname = file_base.format(dir_kind=d, suf=s)
                os.remove(fname)
            except OSError as e:
                if args.verbose:
                    print(f'Failed to remove file {fname}! Error was: {e}')


def load_log_file(args):
    try:
        with open(args.log_file, 'rt', encoding='utf-8') as f:
            logged_data = f.read()
    except OSError as e:
        if args.verbose:
            print(f'Failed to load log file! The error is {e}')
        return dict()
    result = dict()

    for match in LOG_PATTERN.finditer(logged_data):
        matchdict = match.groupdict()
        filename = matchdict.pop('file_name')
        for key, val in matchdict.items():
            matchdict[key] = np.array(list(map(lambda x: float(x[2:]), val.split())))
        result[filename] = matchdict
    return result


def rearrange_files(args):
    file_base_search = os.path.join(args.output_dir, f'{args.current_run_id}', 'orig', '{dir_kind}', '*{suf}')
    last_len = None
    for d, s in zip(OUT_DIRS, OUT_SUFFICES):
        file_search = file_base_search.format(dir_kind=d, suf=s)
        files = sorted(glob.glob(file_search))
        if last_len is None:
            last_len = len(files)
        else:
            if last_len != len(files):
                print(
                    'Whoa, something is seriously wrong! You have different amount of files in each dir!'
                    'I strongly suggest to remove this result and investigate!'
                )
        args.format_width = math.ceil(math.log10(len(files) + 1))
        file_rename = file_search.replace('*', f'{{:0{args.format_width}d}}')
        for i, fname in enumerate(files):
            os.rename(fname, file_rename.format(i))
    return last_len
