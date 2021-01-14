import torch
import sys
import numpy as np
import os
import glob
import pickle

if __name__ == "__main__":
    # State source folder containing grid lidar sweeps
    grid_folder = sys.argv[1]
    # State output folder
    output_folder = sys.argv[2]


    grid = glob.glob(f'{grid_folder}/*.npy')
    import otils
    import inten
    config = otils.io.load_multi_yml('../configs/eval.reflect-l2.depth.rgb.yml')
    config['device'] = 'cpu'
    runner = inten.data.EvalRunner(config)

    weights = torch.load('intensity_weights.pt')

    runner.model.load_state_dict(weights)

    for file in grid:
        with torch.no_grad():
            x = np.load(file)

            ### Data reshaping to get input for neural network
            data = torch.tensor(x, dtype=torch.float).permute(2,0,1).unsqueeze(0)
            input_data = data[:,[0, 5,6,7, 8, 9]]
            input_data[0,0] = input_data[0,0] / 131
            inten = runner.model(input_data)
            reflect = inten[0].permute(2, 3, 0, 1).reshape(-1, 1)[:,0]
            pcl = x.reshape(-1, 11)
            pcl = np.insert(pcl, 4, reflect, 1)

            destination = f'{output_folder}/{os.path.basename(file)}'
            np.save(destination, pcl)
            print(f'{file} stored to {destination} in form of Point cloud')


    ''' Resulting point cloud channels: Depth, x-coor, y-coor, z-coor, Reflectivity, Label, Red, Green, Blue, Colour_mask, Returned_ray_mask'''

    # import pptk
    # v= pptk.viewer(pcl[:,1:4], pcl[:, 4])
