import pickle
from functools import lru_cache
from math import atan2, cos, degrees, radians, sin, tan

import numpy as np

THRESHOLD = 1000
MAXIMUM = np.iinfo(np.uint16).max
PROJECTING = False


def pixel_to_ndc(pixel, size):
    p_y, p_x = pixel
    s_y, s_x = size
    s_y -= 1  # so 1 is being mapped into (n-1)th pixel
    s_x -= 1  # so 1 is being mapped into (n-1)th pixel
    return (-2 / s_y) * p_y + 1, (2 / s_x) * p_x - 1


def pixels_to_ndcs(pixels, size):
    # vectorized version, of above function
    pixels = np.copy(pixels).astype(np.float32)
    if pixels.shape[1] == 2 and pixels.shape[0] != 2:
        pixels = pixels.T
    # pixels are in shape <pixels, 2>
    p_y = pixels[0, :]
    p_x = pixels[1, :]
    s_y, s_x = size
    s_y -= 1  # so 1 is being mapped into (n-1)th pixel
    s_x -= 1  # so 1 is being mapped into (n-1)th pixel
    pixels[0, :] = (-2 / s_y) * p_y + 1
    pixels[1, :] = (2 / s_x) * p_x - 1
    return pixels


def ndc_to_pixel(ndc, size):
    ndc_y, ndc_x = ndc
    s_y, s_x = size
    s_y -= 1  # so 1 is being mapped into (n-1)th pixel
    s_x -= 1  # so 1 is being mapped into (n-1)th pixel
    return (-(s_y / 2) * ndc_y + (s_y / 2), (s_x / 2) * ndc_x + (s_x / 2))


def ndcs_to_pixels(ndcs, size):
    # vectorized version, of above function
    pixels = np.copy(ndcs).astype(np.float32)
    if ndcs.shape[1] == 2 and ndcs.shape[0] != 2:
        ndcs = ndcs.T
    # pixels are in shape <pixels, 2>
    ndc_x = ndcs[0, :]
    ndc_y = ndcs[1, :]
    s_y, s_x = size
    s_y -= 1  # so 1 is being mapped into (n-1)th pixel
    s_x -= 1  # so 1 is being mapped into (n-1)th pixel
    pixels[0, :] = (-s_y / 2) * ndc_y + (s_y / 2)
    pixels[1, :] = (s_x / 2) * ndc_x + (s_x / 2)
    return pixels.astype(np.int32)


def generate_points(width, height):
    x_range = range(0, width)
    y_range = range(0, height)
    points = np.transpose([np.tile(y_range, len(x_range)), np.repeat(x_range, len(y_range))])
    return points


def points_to_homo(res, depth, tresholding=True):
    width = res['width']
    height = res['height']
    size = (height, width)
    proj_matrix = res['proj_matrix']

    if tresholding:
        max_depth = res['cam_far_clip']
        # max_depth = 60 # just for testing
        vec = proj_matrix @ np.array([[1], [1], [-max_depth], [1]])
        # print(vec)
        vec /= vec[3]
        threshold = vec[2]
    else:
        threshold = -np.inf

    if PROJECTING:
        # print('projecting')
        depth[depth < threshold] = threshold  # since 0 is far clip, depth below threshold is behind threshold, and this projects it
    # print('threshold', threshold)
    # vecs = np.zeros((4, points.shape[0]))
    valid_points = np.where(depth >= threshold)
    valid_y, valid_x = valid_points

    vecs = np.zeros((4, len(valid_y)))

    ndcs = pixels_to_ndcs(np.array(valid_points), size)

    vecs[0, :] = ndcs[1, :]
    vecs[1, :] = ndcs[0, :]
    vecs[2, :] = depth[valid_y, valid_x]
    vecs[3, :] = 1  # last, homogenous coordinate
    return vecs, valid_points


def ndc_to_view(vecs, proj_matrix):
    vecs_p = np.linalg.inv(proj_matrix) @ vecs
    vecs_p /= vecs_p[3, :]
    return vecs_p


def view_to_world(vecs_p, view_matrix):
    vecs_p = inv_rigid(view_matrix) @ vecs_p
    vecs_p /= vecs_p[3, :]
    return vecs_p


def is_rotation_matrix(R):
    Rt = np.transpose(R)
    should_be_identity = np.dot(Rt, R)
    I = np.identity(3, dtype=R.dtype)
    n = np.linalg.norm(I - should_be_identity)
    return n < 1e-6


def is_rigid(M):
    return is_rotation_matrix(M[0:3, 0:3]) and np.linalg.norm(M[3, :] - np.array([0, 0, 0, 1], dtype=M.dtype)) < 1e-6


def inv_rigid(M):
    # if we have rigid transformation matrix, we can calculate its inversion analytically, with bigger precision
    assert is_rigid(M)
    Mt = np.zeros_like(M)
    Mt[0:3, 0:3] = np.transpose(M[0:3, 0:3])
    Mt[0:3, 3] = -Mt[0:3, 0:3] @ M[0:3, 3]
    Mt[3, 3] = 1
    return Mt


def ndc_to_real(depth, proj_matrix):
    width = depth.shape[1]
    height = depth.shape[0]

    params = {'width': width, 'height': height, 'proj_matrix': proj_matrix}

    vecs, transformed_points = points_to_homo(params, depth, tresholding=False)
    vec_y, vec_x = transformed_points

    vecs_p = ndc_to_view(vecs, proj_matrix).T

    new_depth = np.copy(depth)
    new_depth[vec_y, vec_x] = vecs_p[:, 2]

    return new_depth


def vfov_to_hfov(H=1080, W=1914, fov=50.0):
    return degrees(2 * atan2(W * tan(radians(fov / 2)), H))


def get_gta_far_clip():
    return 10003.815  # the far clip, rounded value of median, after very weird values were discarded


def construct_proj_matrix(H=1080, W=1914, fov=50.0, near_clip=1.5):
    # for z coord
    f = near_clip  # the near clip, but f in the book
    n = get_gta_far_clip()
    # x coord
    # r = W * n * tan(radians(fov) / 2) / H
    # l = -r
    # y coord
    # t = n * tan(radians(fov) / 2)
    # b = -t
    # x00 = 2*n/(r-l)
    x00 = H / (tan(radians(fov) / 2) * W)
    # x11 = 2*n/(t-b)
    x11 = 1 / tan(radians(fov) / 2)
    # x02 = -(r + l) / (r - l)
    # x12 = -(t + b) / (t - b)
    x02 = 0  # since r == -l, the numerator is 0 and thus whole value is 0
    x12 = 0  # since b == -t, the numerator is 0 and thus whole value is 0
    return np.array([[x00, 0, x02, 0], [0, x11, x12, 0], [0, 0, -f / (f - n), -f * n / (f - n)], [0, 0, -1, 0]])


def proj_matrix_to_near_clip(proj_matrix):
    f = get_gta_far_clip()
    p22 = proj_matrix[2, 2]
    p23 = proj_matrix[2, 3]
    # n_1 and n_2 should be same, so I just assert they are very similar and average them
    n_1 = (p22 * f) / (1 - p22)
    n_2 = (p23 * f) / (p23 + f)
    assert np.isclose(n_1, n_2, atol=5e-6)
    return (n_1 + n_2) / 2


def depth_crop_and_positive(depth):
    depth = np.copy(depth)
    # first we reverse values, so they are in positive values
    depth *= -1
    # then we treshold the far clip so when we scale to integer range
    depth[depth > THRESHOLD] = THRESHOLD
    return depth


def depth_to_integer_range(depth):
    depth = np.copy(depth)
    # then we rescale to as big value as file format allows us
    ratio = MAXIMUM / THRESHOLD
    depth *= ratio
    return depth.astype(np.int32)


def depth_from_integer_range(depth):
    depth = np.copy(depth)
    depth = depth.astype(np.float32)
    # then we rescale to integer32
    ratio = THRESHOLD / MAXIMUM
    depth *= ratio
    return depth


def construct_view_matrix(camera_pos, camera_rotation):
    view_matrix = np.zeros((4, 4))
    # view_matrix[0:3, 3] = camera_pos
    view_matrix[0:3, 0:3] = create_rot_matrix(camera_rotation)
    view_matrix[3, 3] = 1

    trans_matrix = np.eye(4)
    trans_matrix[0:3, 3] = -camera_pos

    # return view_matrix
    return view_matrix @ trans_matrix


def create_rot_matrix(rot):
    x = np.radians(rot[0])
    y = np.radians(rot[1])
    z = np.radians(rot[2])

    Rx = np.array([[1, 0, 0], [0, sin(x), cos(x)], [0, cos(x), -sin(x)]], dtype=np.float)
    Ry = np.array([[cos(y), 0, -sin(y)], [0, 1, 0], [sin(y), 0, cos(y)]], dtype=np.float)
    Rz = np.array([[cos(z), sin(z), 0], [sin(z), -cos(z), 0], [0, 0, 1]], dtype=np.float)
    result = Rx @ Ry @ Rz
    return result


def homo_world_coords_to_pixel(point_homo, view_matrix, proj_matrix, width, height):
    viewed = view_matrix @ point_homo
    projected = proj_matrix @ viewed
    # following row works for partially visible cars, not for cars completely outside of the frustum
    projected[0:3, projected[3] < 0] *= -1  # this row is very important. It fixed invalid projection of points outside the camera view frustum
    projected /= projected[3]
    to_pixel_matrix = np.array([[width / 2, 0, 0, width / 2], [0, -height / 2, 0, height / 2]])
    in_pixels = to_pixel_matrix @ projected
    return in_pixels


def world_coords_to_pixel(pos, view_matrix, proj_matrix, width, height):
    point_homo = np.array([pos[0], pos[1], pos[2], 1])
    return homo_world_coords_to_pixel(point_homo, view_matrix, proj_matrix, width, height)


def model_coords_to_pixel(model_pos, model_rot, positions, view_matrix, proj_matrix, width, height):
    point_homo = np.array([positions[:, 0], positions[:, 1], positions[:, 2], np.ones_like(positions[:, 0])])
    model_matrix = construct_model_matrix(model_pos, model_rot)
    world_point_homo = model_matrix @ point_homo
    # print('world_point_homo.shape', world_point_homo.shape)
    return homo_world_coords_to_pixel(world_point_homo, view_matrix, proj_matrix, width, height)


def create_model_rot_matrix(rot):
    x = np.radians(rot[0])
    y = np.radians(rot[1])
    z = np.radians(rot[2])

    Rx = np.array([[1, 0, 0], [0, cos(x), -sin(x)], [0, sin(x), cos(x)]], dtype=np.float)
    Ry = np.array([[cos(y), 0, sin(y)], [0, 1, 0], [-sin(y), 0, cos(y)]], dtype=np.float)
    Rz = np.array([[cos(z), -sin(z), 0], [sin(z), cos(z), 0], [0, 0, 1]], dtype=np.float)
    result = Rz @ Ry @ Rx
    return result


def construct_model_matrix(position, rotation):
    view_matrix = np.zeros((4, 4))
    # view_matrix[0:3, 3] = camera_pos
    view_matrix[0:3, 0:3] = create_model_rot_matrix(rotation)
    view_matrix[0:3, 3] = position
    view_matrix[3, 3] = 1

    return view_matrix


def get_model_3dbbox(model_sizes):
    x_min, x_max, y_min, y_max, z_min, z_max = model_sizes
    # preparing points of cuboid0
    points_3dbbox = np.array(
        [
            [x_min, y_min, z_min],  # 0 rear left ground
            [x_min, y_min, z_max],  # 1 rear left top
            [x_min, y_max, z_min],  # 2 front left ground
            [x_min, y_max, z_max],  # 3 front left top
            [x_max, y_min, z_min],  # 4 rear right ground
            [x_max, y_min, z_max],  # 5 rear right top
            [x_max, y_max, z_min],  # 6 front right ground
            [x_max, y_max, z_max],  # 7 front right top
        ]
    )
    return points_3dbbox


def model_coords_to_world(model_pos, model_rot, positions):
    point_homo = np.array([positions[:, 0], positions[:, 1], positions[:, 2], np.ones_like(positions[:, 0])])
    model_matrix = construct_model_matrix(model_pos, model_rot)
    world_point_homo = model_matrix @ point_homo

    world_point_homo /= world_point_homo[3, :]
    return world_point_homo.T[:, 0:3]


def model_coords_to_ndc(model_pos, model_rot, positions, view_matrix, proj_matrix):
    point_homo = np.array([positions[:, 0], positions[:, 1], positions[:, 2], np.ones_like(positions[:, 0])])
    model_matrix = construct_model_matrix(model_pos, model_rot)
    point_homo = model_matrix @ point_homo
    viewed = view_matrix @ point_homo
    projected = proj_matrix @ viewed
    projected /= projected[3, :]
    return projected.T[:, 0:3]


@lru_cache(maxsize=8)
def get_pixels_meshgrid(width, height):
    # this shall be called per entity in image, this saves the data
    cc, rr = np.meshgrid(range(width), range(height))
    return cc, rr


@lru_cache(maxsize=8)
def get_pixels_3d_cached(depth, proj_matrix, view_matrix, width, height):
    # pickle should be pickle in C, thus faster
    depth = pickle.loads(depth)
    proj_matrix = pickle.loads(proj_matrix)
    view_matrix = pickle.loads(view_matrix)
    return get_pixels_3d(depth, proj_matrix, view_matrix, width, height)


def get_pixels_3d(depth, proj_matrix, view_matrix, width, height):
    data = {'width': width, 'height': height, 'proj_matrix': proj_matrix}
    # this shall be called per entity in image, this saves the data
    pts, _ = points_to_homo(data, depth, tresholding=False)  # False to get all pixels
    pts_p = ndc_to_view(pts, proj_matrix)
    pixel_3d = view_to_world(pts_p, view_matrix)
    pixel_3d = np.reshape(pixel_3d, (4, height, width))
    pixel_3d = pixel_3d[0:3, ::]
    return pixel_3d


def are_behind_plane(x0, x1, x2, x, y, z):
    v1 = x1 - x0
    v2 = x2 - x0
    n = np.cross(v1, v2)

    return n[0] * (x - x0[0]) + n[1] * (y - x0[1]) + n[2] * (z - x0[2]) > 0


def get_pixels_inside_3d_bbox_mask(bbox, car_mask, depth, bbox_3d_world_homo, proj_matrix, view_matrix, width, height):
    # instance segmentation, for vehicle stencil id pixels, checking if depth pixels are inside 3d bbox in world coordinates
    # and comparing number of these depth pixels in and outside 3d bbox to determine the visibility
    cc, rr = get_pixels_meshgrid(width, height)
    # pickle is C implementation of pickle, very fast. This is the best and fastest way to serialize and deserialize numpy arrays. Thus great for caching
    pixel_3d = get_pixels_3d_cached(pickle.dumps(depth), pickle.dumps(proj_matrix), pickle.dumps(view_matrix), width, height)
    # pixel_3d = get_pixels_3d(depth, proj_matrix, view_matrix, width, height)      # non cached version, slower

    bbox_3d_world_homo /= bbox_3d_world_homo[3, :]
    bbox_3d_world = bbox_3d_world_homo[0:3, :].T

    # points inside the 2D bbox with car mask on
    car_pixels_mask = (car_mask == True) & (cc >= bbox[1, 0]) & (cc <= bbox[0, 0]) & (rr >= bbox[1, 1]) & (rr <= bbox[0, 1])
    # must be == True, because this operator is overloaded to compare every element with True value
    idxs = np.where(car_pixels_mask)

    # 3D coordinates of pixels in idxs
    x = pixel_3d[0, ::].squeeze()[idxs]
    y = pixel_3d[1, ::].squeeze()[idxs]
    z = pixel_3d[2, ::].squeeze()[idxs]

    # test if the points lie inside 3D bbox
    in1 = are_behind_plane(bbox_3d_world[3, :], bbox_3d_world[2, :], bbox_3d_world[7, :], x, y, z)
    in2 = are_behind_plane(bbox_3d_world[1, :], bbox_3d_world[5, :], bbox_3d_world[0, :], x, y, z)
    in3 = are_behind_plane(bbox_3d_world[6, :], bbox_3d_world[2, :], bbox_3d_world[4, :], x, y, z)
    in4 = are_behind_plane(bbox_3d_world[3, :], bbox_3d_world[7, :], bbox_3d_world[1, :], x, y, z)
    in5 = are_behind_plane(bbox_3d_world[7, :], bbox_3d_world[6, :], bbox_3d_world[5, :], x, y, z)
    in6 = are_behind_plane(bbox_3d_world[0, :], bbox_3d_world[2, :], bbox_3d_world[1, :], x, y, z)
    is_inside = in1 & in2 & in3 & in4 & in5 & in6
    return is_inside


def is_entity_in_image(depth, stencil, row, view_matrix, proj_matrix, width, height, vehicle_stencil_ratio=0.4, depth_in_bbox_ratio=0.5):
    # at least 40% of pixels have to be vehicle stencil
    pos = np.array(row['pos'])
    rot = np.array(row['rot'])
    # todo: add entity visibility checking based on stencil data
    model_sizes = np.array(row['model_sizes'])
    bbox_3d_model = get_model_3dbbox(model_sizes)

    # calculating model_coords_to_ndc, so we have both ndc and viewed points
    bbox_3d_model_homo = np.array([bbox_3d_model[:, 0], bbox_3d_model[:, 1], bbox_3d_model[:, 2], np.ones_like(bbox_3d_model[:, 0])])
    model_matrix = construct_model_matrix(pos, rot)
    bbox_3d_world_homo = model_matrix @ bbox_3d_model_homo
    viewed = view_matrix @ bbox_3d_world_homo
    projected = proj_matrix @ viewed
    projected /= projected[3, :]
    bbox_3d_ndc = projected.T[:, 0:3]

    bbox_2d = bbox_3d_ndc[:, 0:2]
    # test if points are inside NDC cuboid by X and Y
    in_ndc = ((bbox_2d[:, 0] > -1) & (bbox_2d[:, 0] < 1) & (bbox_2d[:, 1] > -1) & (bbox_2d[:, 1] < 1)).any()
    # test if points are behind near clip (if they are, they should be in image)
    behind_near_clip = (viewed[2] < 0).any()  # assuming near clip is negative here, which means classical near clip

    # the new strategy is only to check cars with bbox infinities.
    # this car is either not seen or it is partly in the image.
    # Being partly in the image can be checked by some point being behind ans some poins
    # in front of near cam plane
    # return (viewed[2] < 0).any() and (viewed[2] > 0).any()

    # do this test only for entities which can not be excluded otherwise
    if not in_ndc or not behind_near_clip:
        return False

    # the 2d bbox, rectangle
    bbox = np.array(
        calculate_2d_bbox_cached(
            tuple(row['pos']), tuple(row['rot']), tuple(row['model_sizes']), pickle.dumps(view_matrix), pickle.dumps(proj_matrix), width, height
        )
    )
    # bbox = np.array(calculate_2d_bbox(row['pos'], row['rot'], row['model_sizes'], view_matrix, proj_matrix, width, height))
    bbox[:, 0] *= width
    bbox[:, 1] *= height
    bbox = np.array([[np.ceil(bbox[0, 0]), np.floor(bbox[0, 1])], [np.ceil(bbox[1, 0]), np.floor(bbox[1, 1])]]).astype(int)

    # checking the stencil inside 2D bounding box
    vehicle_stencil_id = 2
    # bitwise with 7 sets all flags to zero and keeps only stencil ids
    car_mask = np.bitwise_and(stencil, 7) == vehicle_stencil_id
    car_mask_in_bbox = car_mask[bbox[1, 1] : bbox[0, 1], bbox[1, 0] : bbox[0, 0]]
    if car_mask_in_bbox.mean() < vehicle_stencil_ratio:
        return False

    # test of obstacles, if 3d coord of point where middle of entity should be, is in correct depth
    pixel_pos = world_coords_to_pixel(pos, view_matrix, proj_matrix, width, height)
    pix_x, pix_y = pixel_pos.astype(int)
    ndc_y, ndc_x = pixel_to_ndc((pix_y, pix_x), (height, width))
    if ndc_x < -1 or ndc_x > 1 or ndc_y < -1 or ndc_y > 1:
        # position is not in the image (e.g. partially visible objects)
        # so I can not evaluate it and thus I say it is ok, since this test is only for excluding some cars
        return True

    is_inside = get_pixels_inside_3d_bbox_mask(bbox, car_mask, depth, bbox_3d_world_homo, proj_matrix, view_matrix, width, height)
    return is_inside.mean() >= depth_in_bbox_ratio


# https://stackoverflow.com/questions/3252194/numpy-and-line-intersections
# def perp( a ) :
#     b = np.empty_like(a)
#     b[0] = -a[1]
#     b[1] = a[0]
#     return b
# def seg_intersect(p1, p2) :
#     a1, a2 = np.array(p1)
#     b1, b2 = np.array(p2)
#     da = a2-a1
#     db = b2-b1
#     dp = a1-b1
#     dap = perp(da)
#     denom = np.dot( dap, db)
#     num = np.dot( dap, dp )
#     return (num / denom.astype(float))*db + b1


def ccw(a, b, c):
    return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])


# Return true if line segments AB and CD intersect


def are_intersecting(l1, l2):
    a, b = l1
    c, d = l2
    return ccw(a, c, d) != ccw(b, c, d) and ccw(a, b, c) != ccw(a, b, d)


# taken from https://stackoverflow.com/questions/20677795/how-do-i-compute-the-intersection-point-of-two-lines-in-python
def line_intersection(line1, line2):
    xdiff = (line1[0][0] - line1[1][0], line2[0][0] - line2[1][0])
    ydiff = (line1[0][1] - line1[1][1], line2[0][1] - line2[1][1])  # Typo was here

    def det(a, b):
        return a[0] * b[1] - a[1] * b[0]

    div = det(xdiff, ydiff)
    if div == 0:
        raise Exception('lines do not intersect')

    d = (det(*line1), det(*line2))
    x = det(d, xdiff) / div
    y = det(d, ydiff) / div
    return x, y


def calculate_2d_bbox_pixels(pos, rot, model_sizes, view_matrix, proj_matrix, width, height):
    bbox_2d = np.array(
        calculate_2d_bbox_cached(tuple(pos), tuple(rot), tuple(model_sizes), pickle.dumps(view_matrix), pickle.dumps(proj_matrix), width, height)
    )
    # bbox_2d = np.array(calculate_2d_bbox(pos, rot, model_sizes, view_matrix, proj_matrix, width, height))
    bbox_2d[:, 0] *= width
    bbox_2d[:, 1] *= height
    return bbox_2d


# @fnc.memoize    # DO NOT use the datamatrix memoize function, it is not threadsafe
@lru_cache(maxsize=64)
def calculate_2d_bbox_cached(pos, rot, model_sizes, view_matrix, proj_matrix, width, height):
    pos = list(pos)
    rot = list(rot)
    model_sizes = list(model_sizes)
    proj_matrix = pickle.loads(proj_matrix)
    view_matrix = pickle.loads(view_matrix)
    return calculate_2d_bbox(pos, rot, model_sizes, view_matrix, proj_matrix, width, height)


def calculate_2d_bbox(pos, rot, model_sizes, view_matrix, proj_matrix, width, height):
    pos = np.array(pos)
    rot = np.array(rot)
    model_sizes = np.array(model_sizes)
    points_3dbbox = get_model_3dbbox(model_sizes)
    # calculating model_coords_to_ndc, so we have both ndc and viewed points
    points_3dbbox_homo = np.array([points_3dbbox[:, 0], points_3dbbox[:, 1], points_3dbbox[:, 2], np.ones_like(points_3dbbox[:, 0])])
    model_matrix = construct_model_matrix(pos, rot)
    points_3dbbox_homo = model_matrix @ points_3dbbox_homo
    viewed = view_matrix @ points_3dbbox_homo
    projected = proj_matrix @ viewed
    projected /= projected[3, :]
    bbox_3d = projected.T[:, 0:3]

    bbox_2d_points_ndc = bbox_3d[:, 0:2]
    is_3d_bbox_partially_outside = (bbox_2d_points_ndc < -1).any() or (bbox_2d_points_ndc > 1).any()
    bbox_2d_points_ndc = bbox_2d_points_ndc[((bbox_2d_points_ndc <= 1) & (bbox_2d_points_ndc >= -1)).all(axis=1)]
    if is_3d_bbox_partially_outside:
        bbox_2d = model_coords_to_pixel(pos, rot, points_3dbbox, view_matrix, proj_matrix, width, height).T
        # now we need to compute intersections between end of image and points
        # now we build 12 lines for 3d bounding box
        lines = list()
        lines.append([bbox_2d[0, :], bbox_2d[1, :]])
        lines.append([bbox_2d[1, :], bbox_2d[3, :]])
        lines.append([bbox_2d[3, :], bbox_2d[2, :]])
        lines.append([bbox_2d[2, :], bbox_2d[0, :]])

        lines.append([bbox_2d[4, :], bbox_2d[5, :]])
        lines.append([bbox_2d[5, :], bbox_2d[7, :]])
        lines.append([bbox_2d[7, :], bbox_2d[6, :]])
        lines.append([bbox_2d[6, :], bbox_2d[4, :]])

        lines.append([bbox_2d[4, :], bbox_2d[0, :]])
        lines.append([bbox_2d[5, :], bbox_2d[1, :]])
        lines.append([bbox_2d[6, :], bbox_2d[2, :]])
        lines.append([bbox_2d[7, :], bbox_2d[3, :]])

        borders = list()
        borders.append([[0, 0], [0, height]])
        borders.append([[0, height], [width, height]])
        borders.append([[0, 0], [width, 0]])
        borders.append([[width, 0], [width, height]])

        for line in lines:
            for border in borders:
                if are_intersecting(line, border):
                    # this is implementation using sympy.
                    # HOWEVER SYMPY IS NOT THREAD-SAFE, so it breaks when used for multi-threaded batch processing
                    # l1 = Line(Point(line[0][0], line[0][1]), Point(line[1][0], line[1][1]))
                    # l2 = Line(Point(border[0][0], border[0][1]), Point(border[1][0], border[1][1]))
                    # x, y = np.array(next(iter(l1.intersect(l2))), dtype=np.float32)

                    # this does not use sympy and is fully threadsafe
                    x, y = line_intersection(
                        ((line[0][0], line[0][1]), (line[1][0], line[1][1])), ((border[0][0], border[0][1]), (border[1][0], border[1][1]))
                    )
                    ndc_y, ndc_x = pixel_to_ndc((y, x), (height, width))
                    bbox_2d_points_ndc = np.vstack((bbox_2d_points_ndc, [ndc_x, ndc_y]))

    # because of NDC, this 2d bbox extraction looks so weird
    bbox_2d_points_ndc[:, 1] *= -1  # revert the Y axis in NDC (range [-1,1]) so it corresponds to the pixels axes
    bbox_2d_ndc = np.array(
        [[bbox_2d_points_ndc[:, 0].max(), bbox_2d_points_ndc[:, 1].max()], [bbox_2d_points_ndc[:, 0].min(), bbox_2d_points_ndc[:, 1].min()]]
    )
    # rescale from [-1, 1] to [0, 1]
    bbox_2d = (bbox_2d_ndc / 2) + 0.5
    return bbox_2d.tolist()


def get_depth_lut_for_linear_view(proj_matrix, z_meters_min, z_meters_max, z_range):
    X_view, Y_view, Z_view, W_view = np.meshgrid(
        np.linspace(1, 2, 1), np.linspace(1, 2, 1), np.linspace(-z_meters_max, -z_meters_min, z_range), np.linspace(1, 2, 1)
    )
    view_positions = np.vstack([X_view.ravel(), Y_view.ravel(), Z_view.ravel(), W_view.ravel()])
    ndc_positions = proj_matrix @ view_positions
    ndc_positions /= ndc_positions[3, :]
    # ndc_z = np.flip(ndc_positions[2, :], axis=0)
    ndc_z = ndc_positions[2, :]

    return ndc_z


def grid_to_ndc_pcl_linear_view(bool_grid, proj_matrix, z_meters_min, z_meters_max):
    x_range, y_range, z_range = bool_grid.shape
    ndc_z = get_depth_lut_for_linear_view(proj_matrix, z_meters_min, z_meters_max, z_range)
    return grid_to_ndc_pcl_with_lut(bool_grid, ndc_z)


def grid_to_ndc_pcl_with_lut(bool_grid, ndc_z):
    # here bin centers are in lut
    x_range, y_range, z_range = bool_grid.shape

    points = np.argwhere(bool_grid == True)
    points = points.astype(dtype=np.float32)
    # x mapping to ndc
    transformed = pixels_to_ndcs(np.vstack((points[:, 1], points[:, 0])), (y_range, x_range))
    points[:, 0] = transformed[1, :]
    points[:, 1] = transformed[0, :]
    # we can map x and y linearly, but we need to z map hyperbolically, so we use LUT
    points[:, 2] = ndc_z[points[:, 2].astype(np.int32)]
    return points


def model_rot_matrix_to_euler_angles(r):
    sy = np.sqrt(r[0, 0] ** 2 + r[1, 0] ** 2)
    singular = abs(sy) < 1e-6
    if not singular:
        x = np.arctan2(r[2, 1], r[2, 2])
        y = np.arctan2(-r[2, 0], sy)
        z = np.arctan2(r[1, 0], r[0, 0])
    else:
        x = np.arctan2(-r[1, 2], r[1, 1])
        y = np.arctan2(-r[2, 0], sy)
        z = 0
    return np.degrees(np.array([x, y, z]))


def rot_matrix_to_euler_angles(r):
    sy = np.sqrt(r[0, 0] ** 2 + r[0, 1] ** 2)
    singular = abs(sy) < 1e-6
    if not singular:
        x = np.arctan2(-r[2, 2], r[1, 2])
        y = np.arctan2(-r[0, 2], sy)
        z = np.arctan2(r[0, 1], r[0, 0])
    else:
        x = np.arctan2(-r[2, 0], r[1, 0])
        y = np.arctan2(-r[0, 2], sy)
        z = 0  # arbitrarily set because this singular solution leads to x and z rotating around same axis
    return np.degrees(np.array([x, y, z]))


def car_and_relative_cam_to_absolute_cam_rotation_matrix(car_rot, cam_rel_rot):
    world_to_view_m = create_rot_matrix(np.array([0.0, 0.0, 0.0]))
    cam_rel_rot_m = create_model_rot_matrix(cam_rel_rot)
    car_rot_m = create_model_rot_matrix(car_rot)
    cam_rot_m = world_to_view_m @ cam_rel_rot_m.T @ car_rot_m.T
    return cam_rot_m


def relative_and_absolute_camera_to_car_rotation_matrix(cam_rot, cam_rel_rot):
    world_to_view_m = create_rot_matrix(np.array([0.0, 0.0, 0.0]))
    # cam_rot_m = create_model_rot_matrix(cam_rot)
    cam_rot_m = create_rot_matrix(cam_rot)
    cam_rel_rot_m = create_model_rot_matrix(cam_rel_rot)
    car_rot_m = cam_rot_m.T @ world_to_view_m @ cam_rel_rot_m.T
    return car_rot_m


def car_and_relative_cam_to_absolute_cam_rotation_angles(car_rot, cam_rel_rot):
    r = car_and_relative_cam_to_absolute_cam_rotation_matrix(car_rot, cam_rel_rot)
    return rot_matrix_to_euler_angles(r)


def relative_and_absolute_camera_to_car_rotation_angles(cam_rot, cam_rel_rot):
    r = relative_and_absolute_camera_to_car_rotation_matrix(cam_rot, cam_rel_rot)
    return model_rot_matrix_to_euler_angles(r)


def car_and_relative_cam_to_absolute_cam_position(car_pos, car_rot, cam_rel_pos):
    car_matrix = construct_model_matrix(car_pos, car_rot)
    cam_rel_pos = np.concatenate((cam_rel_pos, [1]))
    cam_pos = car_matrix @ cam_rel_pos
    cam_pos /= cam_pos[3]
    return cam_pos[0:3]


def relative_and_absolute_camera_to_car_position(cam_pos, cam_rot, cam_rel_pos, cam_rel_rot):
    r = relative_and_absolute_camera_to_car_rotation_matrix(cam_rot, cam_rel_rot)
    car_rel_position = r @ -cam_rel_pos
    car_position = car_rel_position + cam_pos
    return car_position


def range_overlap(a_min, a_max, b_min, b_max):
    return (a_min <= b_max) and (b_min <= a_max)


def rectangles_overlap(r1, r2):
    r1_right, r1_left = r1[:, 0]
    r1_top, r1_bottom = r1[:, 1]
    r2_right, r2_left = r2[:, 0]
    r2_top, r2_bottom = r2[:, 1]
    return range_overlap(r1_left, r1_right, r2_left, r2_right) and range_overlap(r1_bottom, r1_top, r2_bottom, r2_top)


def get_rectangles_overlap(r1, r2):
    overlap = np.zeros_like(r1)
    overlap[0, :] = np.minimum(r1[0, :], r2[0, :])
    overlap[1, :] = np.maximum(r1[1, :], r2[1, :])
    return overlap


def get_rectangle_volume(r):
    return (r[0, 0] - r[1, 0]) * (r[0, 1] - r[1, 1])


# this is the joblib Cache, can cache even mutable, non-hashable objects, but does not use the decorator
# https://joblib.readthedocs.io/en/latest/auto_examples/memory_basic_usage.html
# memory = Memory('./_cache', verbose=0, bytes_limit=300 * 1024 * 1024)
# these functions take numpy arrays as parameters, that's why I cache them that way
# get_pixels_3d = memory.cache(get_pixels_3d)
# by memory measurement via
# from sys import getsizeof
# getsizeof(some_numpy_array)
# the get_pixels_3d takes 48MB to allocate. So around 300MB cache size should not be too much nor too few

# todo: začít sbírat i polohu a rotaci auta
