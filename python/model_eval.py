import os.path as osp
import sys

import torch.utils.data as data

import inten
import otils as ot
import torchutils as tu

if __name__ == '__main__':
    config = ot.io.load_multi_yml(sys.argv[1])
    if 'seed' in config:
        tu.seed_all(config['seed'])
    cp = ot.checkpoint.load_checkpoint(osp.join(config['base_dir'], config['store_dir'], config['checkpoint']), False)
    runner = inten.data.EvalRunner(config)
    trn_dataset = data.DataLoader(inten.data.Dataset(config['train']), **config['train_loader'])
    val_dataset = data.DataLoader(inten.data.Dataset(config['val']), **config['val_loader'])
    runner.load_checkpoint(cp)
    runner(trn_dataset, osp.join(config['base_dir'], config['store_dir'], config['base_save'], config['train_save']))
    runner(val_dataset, osp.join(config['base_dir'], config['store_dir'], config['base_save'], config['val_save']))
