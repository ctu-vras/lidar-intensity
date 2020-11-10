SCENE_IDS = """SELECT DISTINCT scene_id, timestamp FROM snapshots WHERE run_id = %s ORDER BY timestamp ASC"""

SNAPSHOTS_NUM = """SELECT COUNT(DISTINCT snapshot_id) FROM snapshots WHERE run_id = %s"""

SNAPSHOTS = """SELECT snapshot_id, imagepath, cam_near_clip, camera_fov, width, height, timestamp, timeofday,
      ARRAY[st_x(camera_relative_rotation), st_y(camera_relative_rotation), st_z(camera_relative_rotation)] as camera_relative_rotation,
      ARRAY[st_x(camera_relative_position), st_y(camera_relative_position), st_z(camera_relative_position)] as camera_relative_position,
      ARRAY[st_x(camera_pos), st_y(camera_pos), st_z(camera_pos)] as camera_pos,
      ARRAY[st_x(camera_rot), st_y(camera_rot), st_z(camera_rot)] as camera_rot,
      ARRAY[st_x(current_target), st_y(current_target), st_z(current_target)] as current_target,
      currentweather, scene_id, run_id
      FROM snapshots
      WHERE run_id = %s AND scene_id = %s
      ORDER BY timestamp ASC"""

DELETE_SNAPSHOT = """DELETE FROM snapshots WHERE snapshot_id = %s"""
DELETE_RUN = """DELETE FROM runs WHERE run_id = %s"""

RUNS = """SELECT run_id FROM runs ORDER BY created ASC"""

ENTITIES = """SELECT bbox, ARRAY[st_x(pos), st_y(pos), st_z(pos)] as pos, ARRAY[st_x(rot), st_y(rot), st_z(rot)] as rot,
              ARRAY[st_xmin(bbox3d), st_xmax(bbox3d), st_ymin(bbox3d), st_ymax(bbox3d), st_zmin(bbox3d), st_zmax(bbox3d)] as bbox3d,
              type as typ, class as clazz, handle, snapshot_id
              FROM detections WHERE snapshot_id = %s"""

CAMS = """SELECT DISTINCT
          ARRAY[st_x(camera_relative_rotation), st_y(camera_relative_rotation), st_z(camera_relative_rotation)] as camera_relative_rotation,
          ARRAY[st_x(camera_relative_position), st_y(camera_relative_position), st_z(camera_relative_position)] as camera_relative_position
          FROM snapshots WHERE run_id = %s AND camera_fov != 0"""
