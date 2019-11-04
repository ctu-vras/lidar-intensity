import json
import os
from configparser import ConfigParser

import numpy as np
import scipy.io as sio
from PIL import Image

import gta.visualization
import progressbar
import tifffile
from gta.gta_math import construct_proj_matrix, construct_view_matrix
from gta.visualization import are_buffers_same_as_previous, bbox_from_string, is_first_record_in_run, load_depth, load_stencil
from joblib import Parallel, delayed

ini_file = "gta-postprocessing.ini"
gta.visualization.multi_page = False
gta.visualization.ini_file = ini_file
gta.visualization.use_cache = False

conn = gta.visualization.get_connection_pooled()
cur = conn.cursor()

CONFIG = ConfigParser()
CONFIG.read(ini_file)
in_directory = CONFIG["Images"]["Tiff"]
out_directory = r'E:\datasets\out_velodyne1'

# for some datasets we don't need entities, which produces lot smaller json files
# for some datasets, we want each camera data to be in separate folder
# sometimes buffers are not synced and don't correspond to current camera.
# they can be recognized by having same data as previous record
discard_invalid_buffers = True

# default settings
include_entities = True
directory_per_camera = False
depth_in_tiff = False
scene_index_naming = False
export_depth = True
export_stencil = True


run_id = 648


cur.execute(
    """SELECT snapshot_id, imagepath, cam_near_clip, camera_fov, width, height, timestamp, timeofday, width, height,       ARRAY[st_x(camera_relative_rotation), st_y(camera_relative_rotation), st_z(camera_relative_rotation)] as camera_relative_rotation,       ARRAY[st_x(camera_relative_position), st_y(camera_relative_position), st_z(camera_relative_position)] as camera_relative_position,       ARRAY[st_x(camera_pos), st_y(camera_pos), st_z(camera_pos)] as camera_pos,       ARRAY[st_x(camera_rot), st_y(camera_rot), st_z(camera_rot)] as camera_rot,       ARRAY[st_x(current_target), st_y(current_target), st_z(current_target)] as current_target,       currentweather, scene_id, run_id       FROM snapshots       WHERE run_id = {}
      ORDER BY timestamp ASC \
    """.format(
        run_id
    )
)

results = []
for row in cur:
    res = dict(row)
    if res['camera_fov'] == 0 and res['cam_near_clip'] == 0:
        continue  # somehow malformed data, skipping them
    res['camera_rot'] = np.array(res['camera_rot'])
    res['camera_pos'] = np.array(res['camera_pos'])
    res['camera_relative_rotation'] = np.array(res['camera_relative_rotation'])
    res['camera_relative_position'] = np.array(res['camera_relative_position'])
    res['current_target'] = np.array(res['current_target'])
    res['view_matrix'] = construct_view_matrix(res['camera_pos'], res['camera_rot'])
    res['proj_matrix'] = construct_proj_matrix(res['height'], res['width'], res['camera_fov'], res['cam_near_clip'])
    results.append(res)

print('There are {} snapshots'.format(len(results)))


def get_base_name(name):
    return os.path.basename(os.path.splitext(name)[0])


def get_main_image_name(cameras):
    for cam in cameras:
        # this is the main camera
        if np.array_equal(cam['camera_relative_rotation'], [0, 0, 0]):
            return cam['imagepath']
    raise Exception('no main image')


def load_entities_data(snapshot_id):
    conn = gta.visualization.get_connection_pooled()
    cur = conn.cursor()

    # start = time.time()

    cur.execute(
        """SELECT bbox,         ARRAY[st_x(pos), st_y(pos), st_z(pos)] as pos,         ARRAY[st_x(rot), st_y(rot), st_z(rot)] as rot,         ARRAY[st_xmin(bbox3d), st_xmax(bbox3d), st_ymin(bbox3d), st_ymax(bbox3d), st_zmin(bbox3d), st_zmax(bbox3d)] as bbox3d,          type, class, handle, snapshot_id         FROM detections         WHERE snapshot_id = '{}'         """.format(
            snapshot_id
        )
    )

    # end = time.time()
    # print('time to load from db', end - start)
    # start = time.time()

    # print(size)
    results = []
    for row in cur:
        res = dict(row)
        res['model_sizes'] = np.array(res['bbox3d'])
        res['bbox'] = bbox_from_string(res['bbox'])
        res['pos'] = np.array(res['pos'])
        res['rot'] = np.array(res['rot'])
        results.append(res)

    # end = time.time()
    # print('time to convert arrays to numpy', end - start)
    # start = time.time()

    return results


def convert_rgb(in_directory, out_directory, out_name, name, out_format):
    outfile = os.path.join(out_directory, "{}.{}".format(out_name, out_format))
    # print(outfile)
    if os.path.exists(outfile):
        return

    try:
        infile = os.path.join(in_directory, name)
        im = Image.open(infile)
        im = im.convert(mode="RGB")
        im.save(outfile)
    except OSError:
        # print("Skipping invalid file {}".format(name))
        return


def convert_depth(in_directory, out_directory, out_name, name, out_format):
    outfile = os.path.join(out_directory, "{}.{}".format(out_name, out_format))
    # print(outfile)
    if os.path.exists(outfile):
        return

    try:
        infile = os.path.join(in_directory, name)
        depth = load_depth(infile)
        if out_format in ['png', 'jpg']:
            # print('depth min before: ', np.min(depth))
            # print('depth max before: ', np.max(depth))
            depth = depth * np.iinfo(np.uint16).max
            # print('depth min after: ', np.min(depth))
            # print('depth max after: ', np.max(depth))
            im = Image.fromarray(depth.astype(np.int32), mode="I")
            im.save(outfile)
        elif out_format == 'mat':
            sio.savemat(outfile, {'depth': depth}, do_compression=True)
        elif out_format == 'tiff':
            tifffile.imsave(outfile, depth, compress='lzma')
    except OSError:
        # print("Skipping invalid file {}".format(name))
        return


def convert_stencil(in_directory, out_directory, out_name, name, out_format):
    outfile = os.path.join(out_directory, "{}.{}".format(out_name, out_format))
    # print(outfile)
    if os.path.exists(outfile):
        return

    try:
        infile = os.path.join(in_directory, name)
        stencil = load_stencil(infile)
        im = Image.fromarray(stencil.astype(np.uint8), mode="L")
        im.save(outfile)
    except OSError:
        # print("Skipping invalid file {}".format(name))
        return


def try_dump_snapshot_to_dataset(in_directory, out_directory, res, run_id):
    try:
        dump_snapshot_to_dataset(in_directory, out_directory, res, run_id)
    except Exception as e:
        print(e)
        import traceback

        traceback.print_exc()
        pass


def dump_snapshot_to_dataset(in_directory, out_directory, res, run_id):
    if not os.path.exists(out_directory):
        os.makedirs(out_directory, exist_ok=True)

    if discard_invalid_buffers and (not is_first_record_in_run(res, run_id)) and are_buffers_same_as_previous(res):
        print(
            'skipping record wih invalid buffers in snapshot {}, filename {} and camera {}'.format(
                res['snapshot_id'], res['imagepath'], res['camera_relative_position'].tolist()
            )
        )
        return

    name = res['imagepath']
    out_name = res['imagepath']

    convert_rgb(in_directory, out_directory, out_name, name + '.tiff', 'png')
    if export_depth:
        if depth_in_tiff:
            convert_depth(in_directory, out_directory, out_name + '-depth', name, 'tiff')
        else:
            convert_depth(in_directory, out_directory, out_name + '-depth', name, 'png')

    if export_stencil:
        convert_stencil(in_directory, out_directory, out_name + '-stencil', name, 'png')

    outfile = os.path.join(out_directory, '{}.json'.format(out_name))
    if os.path.exists(outfile):
        return

    if include_entities:
        data = load_entities_data(res['snapshot_id'])

        json_entities_data = []
        for i in data:
            json_entity = {
                'model_sizes': i['model_sizes'].tolist(),
                'bbox': i['bbox'].tolist(),
                'pos': i['pos'].tolist(),
                'rot': i['rot'].tolist(),
                'class': i['class'],
                'handle': i['handle'],
                'type': i['type'],
            }
            json_entities_data.append(json_entity)

    json_data = {
        'imagepath': res['imagepath'],
        'timestamp': res['timestamp'].strftime("%Y-%m-%d %H:%M:%S"),
        'timeofday': res['timeofday'].strftime("%H:%M:%S"),
        'currentweather': res['currentweather'],
        'width': res['width'],
        'height': res['height'],
        'snapshot_id': res['snapshot_id'],
        'scene_id': res['scene_id'],
        'run_id': res['run_id'],
        'camera_rot': res['camera_rot'].tolist(),
        'camera_pos': res['camera_pos'].tolist(),
        'camera_fov': res['camera_fov'],
        'camera_relative_rotation': res['camera_relative_rotation'].tolist(),
        'camera_relative_position': res['camera_relative_position'].tolist(),
        'current_target': res['current_target'].tolist(),
        'view_matrix': res['view_matrix'].tolist(),
        'proj_matrix': res['proj_matrix'].tolist(),
    }

    if include_entities:
        json_data['entities'] = json_entities_data

    with open(outfile, 'w') as f:
        json.dump(json_data, f)


workers = 6
widgets = [progressbar.Percentage(), ' ', progressbar.Counter(), ' ', progressbar.Bar(), ' ', progressbar.FileTransferSpeed()]

pbar = progressbar.ProgressBar(widgets=widgets, maxval=len(results)).start()
counter = 0

Parallel(n_jobs=workers, backend='threading')(
    delayed(try_dump_snapshot_to_dataset)(in_directory, out_directory, i, run_id)
    for i in results
)
print('done')
