# Third-party notices

## Falconsai NSFW image detection model

- Author: Falcons.ai / Falconsai
- Model: [`Falconsai/nsfw_image_detection`](https://huggingface.co/Falconsai/nsfw_image_detection)
- License declared by the model repository: [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)
- Pinned revision: `96cb0d0342c7afb80cab76ecc58b265fa44da256`

The model weights are downloaded from the upstream repository at runtime and
stored in the user's Docker volume. They are not included in this source
repository or the application image. The project's MIT license applies to
the project code, not to the model weights or upstream dependencies.

模型下载后在本机推理；模型声明的评测指标不能视为对用户照片准确率的保证。

## Immich

This is an independent community project that uses Immich's public API.
It is not an official Immich plugin and is not affiliated with or endorsed by
the Immich team. Immich is developed and licensed separately:
[immich-app/immich](https://github.com/immich-app/immich).

## Python dependencies

PyTorch, Transformers, FastAPI, HTTPX, Pillow and other dependencies retain
their own licenses and notices. Refer to the license files distributed with
the installed packages. No upstream license is replaced by this project's
MIT license.
