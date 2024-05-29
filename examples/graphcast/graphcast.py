# Copyright (c) 2024 PaddlePaddle Authors. All Rights Reserved.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from typing import Dict

import hydra
import numpy as np
import paddle
import plot
from omegaconf import DictConfig

import ppsci
from ppsci.data.dataset import atmospheric_dataset


def eval(cfg: DictConfig):
    model = ppsci.arch.GraphCastNet(
        cfg.MODEL.input_keys, cfg.MODEL.output_keys, cfg.graph_config
    )

    # set dataloader config
    eval_dataloader_cfg = {
        "dataset": {
            "name": "GridMeshAtmosphericDataset",
            "input_keys": ("input",),
            "label_keys": ("label",),
            "config": cfg.graph_config,
        },
        "batch_size": cfg.EVAL.batch_size,
        "sampler": {
            "name": "BatchSampler",
            "drop_last": False,
            "shuffle": False,
        },
        "num_workers": 1,
    }

    error_validator = ppsci.validate.SupervisedValidator(
        eval_dataloader_cfg,
        loss=None,
        output_expr={"pred": lambda out: out["pred"]},
        metric=None,
        name="error_validator",
    )

    def loss(
        output_dict: Dict[str, paddle.Tensor],
        label_dict: Dict[str, paddle.Tensor],
        *args,
    ) -> paddle.Tensor:
        graph = output_dict["pred"]
        pred = dataset.denormalize(graph.grid_node_feat.numpy())
        pred = graph.grid_node_outputs_to_prediction(pred, dataset.targets_template)

        target = graph.grid_node_outputs_to_prediction(
            label_dict["label"][0].numpy(), dataset.targets_template
        )

        pred = atmospheric_dataset.dataset_to_stacked(pred)
        target = atmospheric_dataset.dataset_to_stacked(target)
        loss = np.average(np.square(pred.data - target.data))
        return loss

    def metric(
        output_dict: Dict[str, paddle.Tensor],
        label_dict: Dict[str, paddle.Tensor],
        *args,
    ) -> paddle.Tensor:
        graph = output_dict["pred"][0]
        pred = dataset.denormalize(graph.grid_node_feat.numpy())
        pred = graph.grid_node_outputs_to_prediction(pred, dataset.targets_template)

        target = graph.grid_node_outputs_to_prediction(
            label_dict["label"][0].numpy(), dataset.targets_template
        )

        metric_dic = {
            var_name: np.average(target[var_name].data - pred[var_name].data)
            for var_name in list(target)
        }
        return metric_dic

    dataset = error_validator.data_loader.dataset
    error_validator.loss = ppsci.loss.FunctionalLoss(loss)
    error_validator.metric = {"error": ppsci.metric.FunctionalMetric(metric)}

    validator = {error_validator.name: error_validator}

    solver = ppsci.solver.Solver(
        model,
        output_dir=cfg.output_dir,
        log_freq=cfg.log_freq,
        seed=cfg.seed,
        validator=validator,
        pretrained_model_path=cfg.EVAL.pretrained_model_path,
        eval_with_no_grad=cfg.EVAL.eval_with_no_grad,
    )

    solver.eval()

    with solver.no_grad_context_manager(True):
        for index, (input_, label_, _) in enumerate(error_validator.data_loader):
            output_ = model(input_)
            graph = output_["pred"]
            pred = dataset.denormalize(graph.grid_node_feat.numpy())
            pred = graph.grid_node_outputs_to_prediction(pred, dataset.targets_template)

            print(label_["label"])

            target = graph.grid_node_outputs_to_prediction(
                label_["label"][0].numpy(), dataset.targets_template
            )

            plot.log_images(target, pred, "2m_temperature", level=50, file="result.png")


@hydra.main(version_base=None, config_path="./conf", config_name="graphcast_small.yaml")
def main(cfg: DictConfig):
    if cfg.mode == "eval":
        eval(cfg)
    else:
        raise ValueError(f"cfg.mode should in ['eval'], but got '{cfg.mode}'")


if __name__ == "__main__":
    main()