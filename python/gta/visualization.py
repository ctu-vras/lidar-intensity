import os
import re
from configparser import ConfigParser
from functools import lru_cache

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

import psycopg2
import tifffile
from gta_math import calculate_2d_bbox, get_model_3dbbox, model_coords_to_pixel
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from psycopg2.extras import DictCursor
# threaded connection pooling
from psycopg2.pool import PersistentConnectionPool


def get_connection():
    """
    :rtype: connection
    """
    global conn
    if conn is None:
        CONFIG = ConfigParser()
        CONFIG.read(ini_file)
        conn = psycopg2.connect(CONFIG["Postgres"]["db"], cursor_factory=DictCursor)
    return conn


def get_connection_pooled():
    """
    :rtype: connection
    """
    global conn_pool
    if conn_pool is None:
        CONFIG = ConfigParser()
        CONFIG.read(ini_file)
        conn_pool = PersistentConnectionPool(conn_pool_min, conn_pool_max, CONFIG["Postgres"]["db"], cursor_factory=DictCursor)
    conn = conn_pool.getconn()
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    return conn


def get_gta_image_jpg_dir():
    return '/datagrid/personal/racinmat/GTA-jpg'


def bbox_from_string(string):
    return np.array([float(i) for i in re.sub('[()]', '', string).split(',')]).reshape(2, 2)


def get_bounding_boxes(name):
    return get_detections(name, "AND NOT bbox @> POINT '(Infinity, Infinity)'")


def get_detections(name, additional_condition=''):
    name = name.replace('info-', '')
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""SELECT bbox, ARRAY[st_x(pos), st_y(pos), st_z(pos)] as pos,
        ARRAY[st_xmin(bbox3d), st_xmax(bbox3d), st_ymin(bbox3d), st_ymax(bbox3d), st_zmin(bbox3d), st_zmax(bbox3d)] as bbox3d, 
         type, class, handle, detections.snapshot_id
        FROM detections
        JOIN snapshots ON detections.snapshot_id = snapshots.snapshot_id
        WHERE imagepath = '{}' {}
        """.format(name, additional_condition))
    # print(size)
    results = []
    for row in cur:
        res = dict(row)
        res['bbox3d'] = np.array(res['bbox3d'])
        res['bbox'] = bbox_from_string(res['bbox'])
        res['pos'] = np.array(res['pos'])
        results.append(res)
    return results


def get_car_positions(handle, run_id, snapshot_id=None, offset=None):
    conn = get_connection()
    cur = conn.cursor()
    if snapshot_id is None and offset is None:
        cur.execute("""SELECT ARRAY[st_x(pos), st_y(pos), st_z(pos)] as pos
            FROM detections
            JOIN snapshots s2 on detections.snapshot_id = s2.snapshot_id
            WHERE handle = {} and run_id = {}
            ORDER BY created
            """.format(handle, run_id))
    else:
        # only positions [offset] before and after some snapshot id
        assert type(offset) == int
        assert type(snapshot_id) == int
        cur.execute("""SELECT ARRAY[st_x(pos), st_y(pos), st_z(pos)] as pos
            FROM detections
            JOIN snapshots s2 on detections.snapshot_id = s2.snapshot_id
            WHERE handle = {handle} and run_id = {run_id} 
            and s2.snapshot_id < ({snapshot_id} + {offset}) and s2.snapshot_id > ({snapshot_id} - {offset})  
            ORDER BY created
            """.format(handle=handle, run_id=run_id, snapshot_id=snapshot_id, offset=offset))

    # print(size)
    results = []
    for row in cur:
        res = dict(row)
        results.append(res['pos'])
    return results


def calculate_one_entity_bbox(row, view_matrix, proj_matrix, width, height):
    row['bbox_calc'] = calculate_2d_bbox(row['pos'], row['rot'], row['model_sizes'], view_matrix, proj_matrix, width, height)
    pos = np.array(row['pos'])

    bbox = np.array(row['bbox_calc'])
    bbox[:, 0] *= width
    bbox[:, 1] *= height

    # 3D bounding box
    rot = np.array(row['rot'])
    model_sizes = np.array(row['model_sizes'])
    points_3dbbox = get_model_3dbbox(model_sizes)

    # projecting cuboid to 2d
    bbox_2d = model_coords_to_pixel(pos, rot, points_3dbbox, view_matrix, proj_matrix, width, height).T
    # print('3D bbox:\n', points_3dbbox)
    # print('3D bbox in 2D:\n', bbox_2d)
    return bbox, bbox_2d


def load_depth(name):
    if name not in depths:
        if multi_page:
            tiff_depth = Image.open(os.path.join(get_in_directory(), name + '.tiff'))
            tiff_depth.seek(2)
        else:
            tiff_depth = tifffile.imread(os.path.join(get_in_directory(), name + '-depth.tiff'))
        if use_cache:
            depths[name] = tiff_depth
        else:
            return tiff_depth
    return np.copy(depths[name])    # it is being modified, now loaded data dont mutate


def load_stencil(name):
    if name not in stencils:
        if multi_page:
            tiff_stencil = Image.open(os.path.join(get_in_directory(), name + '.tiff'))
            tiff_stencil.seek(1)
            tiff_stencil = np.array(tiff_stencil)
        else:
            tiff_stencil = tifffile.imread(os.path.join(get_in_directory(), name + '-stencil.tiff'))
        if use_cache:
            stencils[name] = tiff_stencil
        else:
            return tiff_stencil
    return np.copy(stencils[name])


def load_stencil_ids(name):
    stencil = load_stencil(name)
    return stencil % 16  # only last 4 bits are object ids


def load_stencil_flags(name):
    stencil = load_stencil(name)
    return stencil - (stencil % 16)  # only first 4 bits are flags


def ids_to_greyscale(arr):
    # there are 4 bits -> 16 values for arrays, transfer from range [0-15] to range [0-255]
    return arr * 4


def show_bboxes(name):
    im = Image.open(os.path.join(get_in_directory(), name + '.tiff'))
    size = (im.size[1], im.size[0])
    fig = plt.figure()
    plt.imshow(im)
    show_bounding_boxes(name, size, plt.gca())
    plt.savefig(os.path.join(out_directory, 'bboxes-' + name + '.jpg'))


@lru_cache(maxsize=8)
def get_first_record_timestamp_in_run(run_id):
    conn = get_connection_pooled()
    cur = conn.cursor()
    cur.execute("""SELECT min(timestamp) as timestamp 
        FROM snapshots 
        WHERE run_id = {} 
        LIMIT 1 
        """.format(run_id))
    return cur.fetchone()['timestamp']


def is_first_record_in_run(res, run_id):
    first_timestamp = get_first_record_timestamp_in_run(run_id)
    return first_timestamp == res['timestamp']


def get_previous_record(res):
    conn = get_connection_pooled()
    cur = conn.cursor()
    cur.execute("""SELECT imagepath, snapshot_id, scene_id 
        FROM snapshots 
        WHERE timestamp < '{}' and run_id = (SELECT run_id from snapshots WHERE snapshot_id = {}) 
        ORDER BY timestamp DESC 
        LIMIT 1 
        """.format(res['timestamp'], res['snapshot_id']))
    # this should select previous record independently on primary key, without problems
    # with race conditions by persisting in other threads
    # and belonging into the same run
    results = []
    for row in cur:
        res = dict(row)
        results.append(res)
    if len(results) == 0:
        print('no previous record for snapshot_id {}'.format(res['snapshot_id']))
    return results[0]['imagepath']


def are_buffers_same_as_previous(res):
    name = res['imagepath']
    depth = load_depth(name)
    stencil = load_stencil(name)
    prev_name = get_previous_record(res)
    prev_depth = load_depth(prev_name)
    prev_stencil = load_stencil(prev_name)
    return (depth == prev_depth).all() or (stencil == prev_stencil).all()


def get_cameras_for_run(run_id):
    # because sometimes I use two cameras heading same direction, pair (position, rotation) is unique identifier
    # camera_fov = 0 happens when some data are corrupted, so this is simple sanity check, but it should happend really rarely
    conn = get_connection_pooled()
    cur = conn.cursor()
    cur.execute("""SELECT DISTINCT \
          ARRAY[st_x(camera_relative_rotation), st_y(camera_relative_rotation), st_z(camera_relative_rotation)] as camera_relative_rotation,
          ARRAY[st_x(camera_relative_position), st_y(camera_relative_position), st_z(camera_relative_position)] as camera_relative_position
          FROM snapshots \
          WHERE run_id = {} AND camera_fov != 0 \
          ORDER BY camera_relative_position, camera_relative_rotation ASC \
        """.format(run_id))

    cam_configurations = []
    camera_names = {}
    for i, row in enumerate(cur):
        # print(row['camera_relative_rotation'])
        # print(row['camera_relative_position'])
        cam_configurations.append((row['camera_relative_rotation'], row['camera_relative_position']))
        camera_name = camera_to_string(row)
        camera_names[camera_name] = str(i)
        # print(camera_name, ': ', i)

    return camera_names, cam_configurations


def camera_to_string(res):
    return 'camera_{}__{}'.format(
        '_'.join(['{:0.2f}'.format(i) for i in res['camera_relative_position']]),
        '_'.join(['{:0.2f}'.format(i) for i in res['camera_relative_rotation']]),
    )


def get_in_directory():
    global in_directory
    if in_directory is None:
        CONFIG = ConfigParser()
        CONFIG.read(ini_file)
        in_directory = CONFIG["Images"]["Tiff"]
    return in_directory


def save_pointcloud_csv(vecs, name, paraview=False):
    if paraview:
        assert (vecs.shape[1] == 4)
    else:
        assert (vecs.shape[1] == 3)
    a = np.asarray(vecs)
    np.savetxt(name, a, delimiter=",")

