import numpy as np


def construct_view_matrix(camera_pos, camera_rotation):
    view_matrix = np.zeros((4, 4))
    view_matrix[0:3, 0:3] = create_rot_matrix(camera_rotation)
    view_matrix[3, 3] = 1

    trans_matrix = np.eye(4)
    trans_matrix[0:3, 3] = -np.array(camera_pos)

    return view_matrix @ trans_matrix


def create_rot_matrix(rot):
    coses = np.cos(np.radians(rot))
    sins = np.sin(np.radians(rot))

    Rx = np.array([[1, 0, 0], [0, sins[0], coses[0]], [0, coses[0], -sins[0]]], dtype=np.float)
    Ry = np.array([[coses[1], 0, -sins[1]], [0, 1, 0], [sins[1], 0, coses[1]]], dtype=np.float)
    Rz = np.array([[coses[2], sins[2], 0], [sins[2], -coses[2], 0], [0, 0, 1]], dtype=np.float)
    result = Rx @ Ry @ Rz
    return result


def construct_proj_matrix(H=1080, W=1914, fov=50.0, near_clip=1.5):
    f = near_clip  # the near clip, but f in the book
    n = 10003.815  # empirical far clip
    x00 = H / (np.tan(np.radians(fov) / 2) * W)
    x11 = 1 / np.tan(np.radians(fov) / 2)

    return np.array([[x00, 0, 0, 0], [0, x11, 0, 0], [0, 0, -f / (f - n), -f * n / (f - n)], [0, 0, -1, 0]])
