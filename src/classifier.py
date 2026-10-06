import io
import threading

from PIL import Image, ImageOps
from .telemetry import emit, error_fields

MODEL_ID='Falconsai/nsfw_image_detection'
MODEL_REVISION='96cb0d0342c7afb80cab76ecc58b265fa44da256'
MODEL_FINGERPRINT=MODEL_ID+'@'+MODEL_REVISION


class Classifier:
    def __init__(self):
        self.lock=threading.Lock()
        self.model=None
        self.processor=None
        self.state='未加载'

    def load(self):
        if self.model is not None:
            return
        self.state='加载/下载模型中'
        emit('model.loading',model=MODEL_ID,revision=MODEL_REVISION,device='cpu')
        try:
            import torch
            from transformers import ViTImageProcessor, ViTForImageClassification
            torch.set_num_threads(2)
            self.processor=ViTImageProcessor.from_pretrained(MODEL_ID,revision=MODEL_REVISION)
            model=ViTForImageClassification.from_pretrained(MODEL_ID,revision=MODEL_REVISION,use_safetensors=True,trust_remote_code=False)
            model.eval()
            self.model=model
        except Exception as e:
            self.state='模型加载失败'
            emit('model.failed',level='ERROR',**error_fields(e))
            raise
        self.state='就绪（CPU，本地）'
        emit('model.ready',device='cpu')

    def predict(self, data):
        with self.lock:
            self.load()
            import torch
            with Image.open(io.BytesIO(data)) as image:
                image=ImageOps.exif_transpose(image).convert('RGB')
                inputs=self.processor(images=image,return_tensors='pt')
            with torch.inference_mode():
                probabilities=self.model(**inputs).logits.softmax(dim=-1)[0]
            scores={self.model.config.id2label[i].lower():float(value) for i,value in enumerate(probabilities)}
            if 'nsfw' not in scores:
                raise ValueError('模型输出没有 nsfw 类别')
            return scores['nsfw']
