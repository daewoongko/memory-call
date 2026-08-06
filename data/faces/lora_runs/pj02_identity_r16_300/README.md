---
base_model: black-forest-labs/FLUX.2-klein-4B
library_name: diffusers
license: other
instance_prompt: portrait photo of pj02person, a Korean man
widget: []
tags:
- text-to-image
- diffusers-training
- diffusers
- lora
- flux2-klein
- flux2-klein-diffusers
- template:sd-lora
---

<!-- This model card has been generated automatically according to the information the training script had access to. You
should probably proofread and complete it, then remove this comment. -->


# Flux.2 [Klein] DreamBooth LoRA - pj02_identity_r16_300

<Gallery />

## Model description

These are the finalized `pj02_identity_r16_300` DreamBooth LoRA weights for
`black-forest-labs/FLUX.2-klein-4B`.

The weights were trained using [DreamBooth](https://dreambooth.github.io/) with the [Flux2 diffusers trainer](https://github.com/huggingface/diffusers/blob/main/examples/dreambooth/README_flux2.md).

Quant training? FP8 TorchAO

## Trigger words

You should use `portrait photo of pj02person, a Korean man` to trigger the image generation.

## Download model

[Download the *.safetensors LoRA](pj02_identity_r16_300/tree/main) in the Files & versions tab.

## Use it with the [🧨 diffusers library](https://github.com/huggingface/diffusers)

```py
from diffusers import AutoPipelineForText2Image
import torch
pipeline = AutoPipelineForText2Image.from_pretrained("black-forest-labs/FLUX.2", torch_dtype=torch.bfloat16).to('cuda')
pipeline.load_lora_weights('pj02_identity_r16_300', weight_name='pytorch_lora_weights.safetensors')
image = pipeline('portrait photo of pj02person, a Korean man').images[0]
```

For more details, including weighting, merging and fusing LoRAs, check the [documentation on loading LoRAs in diffusers](https://huggingface.co/docs/diffusers/main/en/using-diffusers/loading_adapters)

## License

Please adhere to the licensing terms as described [here](https://huggingface.co/black-forest-labs/FLUX.2/blob/main/LICENSE.md).


## Intended uses & limitations

#### How to use

```python
# TODO: add an example code snippet for running this diffusion pipeline
```

#### Limitations and bias

[TODO: provide examples of latent issues and potential remediations]

## Training details

[TODO: describe the data used to train the model]
