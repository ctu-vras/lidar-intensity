#!/usr/bin/env python

import argparse
import builtins
import functools
import sys
import traceback

import multiprocess as mp

import datatools

_orig_print = builtins.print


def nprint(*args, **kwargs):
    _orig_print(mp.current_process()._identity[0], flush=True, end=': ', **kwargs)
    _orig_print(*args, **kwargs, flush=True)


builtins.print = nprint


def try_del(entry, attr):
    try:
        delattr(entry, attr)
    except FileNotFoundError:
        pass


def access(did, data, del_data):
    try:
        entry = data[did]
        print(f'{did}: {entry.velodyne_grid.shape}')
        if del_data:
            for i in range(did, did + 4):
                for attr in ['pcl', 'ego_pcl', 'bbox_data']:
                    try_del(data[i], attr)
    except Exception as e:
        print(e, file=sys.stdout)
        print(traceback.format_exc(), file=sys.stdout)


def parse_args():
    parser = argparse.ArgumentParser('Create velodyne data')
    parser.add_argument('in_dir', help='Dataset directory. The directory shoud have a structure {in_dir}/orig/orig-{json,rgb,depth,stencil}')
    parser.add_argument('-np', '--num_processes', default=mp.cpu_count() // 2, type=int, help='Number of processes to use')
    parser.add_argument('-dt', '--delete_tmp', default=False, action='store_true', help='Whether to delete temporary files')
    return parser.parse_args()


if __name__ == '__main__':
    parsed = parse_args()
    dataset = datatools.gta.GTADataset(parsed.in_dir, width=4)
    f = functools.partial(access, data=dataset, del_data=parsed.delete_tmp)
    with mp.Pool(parsed.num_processes) as pool:
        pool.map(f, range(0, len(dataset), 4))
