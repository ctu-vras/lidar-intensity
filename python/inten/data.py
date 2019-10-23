import argparse
import glob
import itertools as it
import os
import os.path as osp
import sys

import numpy as np
import torch
from PIL import Image

import otils as ot
import torchutils as tu

from . import modules, squeezeseg, utils


class Dataset(tu.SimpleDataset):
    def __init__(self, config):
        folder = config['folder']
        name = config['name']
        if 'ext' in config:
            ext = config['ext']
        else:
            ext = '.npy'
        if 'shuffle' in config:
            shuffle = config['shuffle']
        else:
            shuffle = True
        if 'keep_ram' in config:
            keep_ram = config['keep_ram']
        else:
            keep_ram = True
        self.channels = config['channels']
        if 'limits' in config:
            self.limits = config['limits']
        else:
            self.limits = None
        super().__init__(folder, name=name, ext=ext, shuffle=shuffle, keep_ram=keep_ram)

    def load_and_transform(self, fname, key):
        loaded_data = np.load(fname)
        if self.limits is not None:
            loaded_data = loaded_data[self.limits[0]['min'] : self.limits[0]['max'], self.limits[1]['min'] : self.limits[1]['max'], :]
        result = dict()
        result['key'] = key
        for channel in self.channels:
            tmp = loaded_data[..., channel['start'] : channel['end']]
            if len(tmp.shape) != 3:
                tmp = tmp[..., None]
            if 'scale' in channel:
                tmp = (tmp - channel['scale']['min']) / (channel['scale']['max'] - channel['scale']['min'])
            if 'retype' in channel:
                tmp = tmp.astype(channel['retype'])
            tmp = np.transpose(tmp, (2, 0, 1))
            if 'squeeze' in channel and channel['squeeze']:
                tmp = np.squeeze(tmp)
            result[channel['name']] = tmp
        return result

    def scan_files(self):
        return sorted(glob.glob(osp.join(self.folder, '*' + self.ext)))


class EvalRunner(tu.Runner):
    def __init__(self, config):
        self.config = config
        device = torch.device(self.config['device'])
        model = squeezeseg.SqueezeWithHead.load_from_kwargs(self.config['model']).to(device)
        if 'embed' in self.config:
            embed = utils.Embed(self.config['embed']).to(device)
            embed_channel = self.config['embed_channel']
        else:
            embed, embed_channel = None, None
        optimizer = None
        loss_fn = utils.create_loss_from_kwargs(**self.config['loss'])
        pass_keys = self.config['pass_keys']
        gt_keys = self.config['gt_keys']
        keep_ram = self.config.get('keep_ram', True)
        cat_channels = self.config.get('cat_channels', False)
        self.image_fn = utils.create_image_fn(**self.config['image_fn'])
        self.store_dir = None
        self.info_fn = utils.info_fn(**self.config['info_fn'])
        self.info_accum = dict()

        super().__init__(
            model,
            loss_fn,
            optimizer,
            pass_keys,
            gt_keys,
            verbose=True,
            args=argparse.Namespace(keep_ram=keep_ram, cuda=True),
            use_tqdm=True,
            accum_losses=True,
            cat_channels=cat_channels,
            pass_as_kwargs=True,
            embedder=embed,
            embed_channel=embed_channel,
        )

    def __call__(self, dataloader, store_dir):
        self.store_dir = store_dir
        super().__call__(dataloader, tu.TorchMode.EVAL)
        self.store_dir = None

    def load_checkpoint(self, cp):
        if self.embedder is not None and cp['embed'] is not None:
            self.embedder.load_state_dict(cp['embed'])
        self.model.load_state_dict(cp['state_dict'])

    def run_after_iter(self, batch, output, loss, mode, did, batch_id, _, dataset):
        for i in range(len(batch['key'])):
            result, score = self.image_fn(batch, output, i)
            os.makedirs(self.store_dir, exist_ok=True)
            Image.fromarray(result).save(
                osp.join(self.store_dir, f'{score:.4f}-{osp.splitext(osp.basename(dataset.files[batch["key"][i]]))[0]}.png')
            )
        info = self.info_fn(batch, output)
        if self.info_accum[(dataset, mode)] is None:
            self.info_accum[(dataset, mode)] = info
        else:
            self.info_accum[(dataset, mode)] += info

    def run_pre_epoch(self, dataset, mode):
        self.info_accum[(dataset, mode)] = None

    def run_after_epoch(self, dataset, mode):
        acc_info = self.info_accum[(dataset, mode)]
        classes = (acc_info.shape[0] - 2) // 3
        error = acc_info[0] / acc_info[-1].float()
        extra_string = f'\nMean error for mode: {mode.name}:\t{error:8.4f}\n'

        for c in range(classes):
            iou = acc_info[c * 3 + 1].float() / acc_info[c * 3 + 1 : (c + 1) * 3 + 1].sum()
            precision = acc_info[c * 3 + 1].float() / (acc_info[c * 3 + 1] + acc_info[c * 3 + 2])
            recall = acc_info[c * 3 + 1].float() / (acc_info[c * 3 + 1] + acc_info[(c + 1) * 3])
            extra_string += f'Stats for class {c}:\tIOU: {iou:8.4f}\tPrecision: {precision:8.4f}\tRecall: {recall:8.4f}\n'
        extra_string += '---\n'
        return extra_string


class Runner(tu.Runner):
    def __init__(self, config):
        self.config = config
        device = torch.device(self.config['device'])
        model = squeezeseg.SqueezeWithHead.load_from_kwargs(self.config['model']).to(device)
        if 'embed' in self.config:
            embed = utils.Embed(self.config['embed']).to(device)
            optimizer = utils.create_optim_from_kwargs(it.chain(model.parameters(), embed.parameters()), **self.config['optim'])
            embed_channel = self.config['embed_channel']
        else:
            embed = None
            optimizer = utils.create_optim_from_kwargs(model.parameters(), **self.config['optim'])
            embed_channel = None
        loss_fn = utils.create_loss_from_kwargs(**self.config['loss'])
        pass_keys = self.config['pass_keys']
        gt_keys = self.config['gt_keys']
        keep_ram = self.config.get('keep_ram', True)
        cat_channels = self.config.get('cat_channels', False)
        self.info_fn = utils.info_fn(**self.config['info_fn'])
        self.info_accum = dict()

        super().__init__(
            model,
            loss_fn,
            optimizer,
            pass_keys,
            gt_keys,
            verbose=True,
            args=argparse.Namespace(keep_ram=keep_ram, cuda=True),
            use_tqdm=True,
            accum_losses=True,
            cat_channels=cat_channels,
            pass_as_kwargs=True,
            embedder=embed,
            embed_channel=embed_channel,
        )

    def run_pre_epoch(self, dataset, mode):
        self.info_accum[(dataset, mode)] = None

    def run_after_iter(self, batch, output, loss, mode, did, batch_id, total_batches, dataset):
        info = self.info_fn(batch, output)
        if self.info_accum[(dataset, mode)] is None:
            self.info_accum[(dataset, mode)] = info
        else:
            self.info_accum[(dataset, mode)] += info

    def run_after_epoch(self, dataset, mode):
        if mode is tu.TorchMode.TRAIN:
            os.makedirs(osp.join(self.config['base_dir'], self.config['store_dir']), exist_ok=True)
            ot.checkpoint.store_checkpoint(
                osp.join(self.config['base_dir'], self.config['store_dir'], f'{self.run_times[dataset]:03d}'),
                {
                    'state_dict': self.model.state_dict(),
                    'loss_mean': np.mean([d.cpu().numpy() for d in self.run_losses[dataset]]),
                    'embed': self.embedder.state_dict() if self.embedder is not None else None,
                    'optim': self.optimizer.state_dict(),
                },
                [sys.modules[__name__.split('.')[0]]],
                time_format=None,
                overwrite=True,
            )
        acc_info = self.info_accum[(dataset, mode)]
        classes = (acc_info.shape[0] - 2) // 3
        error = acc_info[0] / acc_info[-1].float()
        extra_string = f'\nMean error for epoch {self.run_times[dataset]:03d} and mode: {mode.name}:\t{error:8.4f}\n'

        for c in range(classes):
            iou = acc_info[c * 3 + 1].float() / acc_info[c * 3 + 1 : (c + 1) * 3 + 1].sum()
            precision = acc_info[c * 3 + 1].float() / (acc_info[c * 3 + 1] + acc_info[c * 3 + 2])
            recall = acc_info[c * 3 + 1].float() / (acc_info[c * 3 + 1] + acc_info[(c + 1) * 3])
            extra_string += f'Stats for class {c}:\tIOU: {iou:8.4f}\tPrecision: {precision:8.4f}\tRecall: {recall:8.4f}\n'
        extra_string += '---\n'
        return extra_string

    def __call__(self, dataloader, mode):
        super().__call__(dataloader, mode)
        return sum(self.run_losses[dataloader.dataset]) / len(dataloader.dataset)

class RGB2GSRunner(EvalRunner):
    def __init__(self, config):
        self.config = config
        device = torch.device(self.config['device'])
        model = modules.RGB2GS(as_tuple=True).to(device)
        optimizer = None
        loss_fn = utils.create_loss_from_kwargs(**self.config['loss'])
        pass_keys = ['rgb']
        gt_keys = ['intensity', 'mask', 'rgb_mask']
        keep_ram = self.config.get('keep_ram', True)
        cat_channels = self.config.get('cat_channels', False)
        self.image_fn = utils.create_image_fn(**self.config['image_fn'])
        self.info_fn = utils.info_fn(**self.config['info_fn'])
        self.info_accum = dict()
        self.store_dir = None

        super(EvalRunner, self).__init__(
            model,
            loss_fn,
            optimizer,
            pass_keys,
            gt_keys,
            verbose=True,
            args=argparse.Namespace(keep_ram=keep_ram, cuda=True),
            use_tqdm=True,
            accum_losses=True,
            cat_channels=cat_channels,
            pass_as_kwargs=True,
            embedder=None,
            embed_channel=None,
        )
