import base64
import hashlib
from PIL import Image
from io import BytesIO
from math import sqrt
import os
from os import path
class ImageObject:
    """图片对象，包含 base64 编码的图片数据"""
    image_id: str
    url: str
    def __init__(self, image_id: str, url: str):
        self.image_id = image_id
        self.url = url

def img2bytes(img: Image.Image, max_bytes=500000):
    if (img.mode == "P"):
        img = img.convert("RGBA")
    if ("A" in img.mode):
        fmt = "PNG"
        kwa = {}
    else:
        fmt = "JPEG"
        kwa = {"quality": 90}
    w, h = img.size
    def to_bytes(ratio):
        w1, h1 = round(ratio*w), round(ratio*h)
        bio = BytesIO()
        img.resize((w1, h1), resample=Image.Resampling.LANCZOS).save(bio, format=fmt, **kwa)
        size = bio.tell()
        
        bio.seek(0)
        data = bio.read()

        bio.seek(0)
        
        return bio, data, size
    
    ratio = 1
    while (ratio*w>1 and ratio*h>1):
        bio, data, size = to_bytes(ratio)
        if (size<=max_bytes):
            return fmt, bio, data, size
        else:
            ratio = min(ratio*0.9, ratio*sqrt(max_bytes/size))

def img2b64url(img: Image.Image, max_bytes=500000):
    fmt, bio, data, size = img2bytes(img, max_bytes=max_bytes)

    if (fmt == "PNG"):
        mime = "image/png"
    elif (fmt == "JPEG"):
        mime = "image/jpeg"
    else:
        raise ValueError("Format="+str(fmt))

    b64 = base64.b64encode(data).decode("ascii")

    url = f"data:{mime};base64,{b64}"
    return url

class ImagePIL(ImageObject):
    def __init__(self, im: Image.Image, image_id=None):
        if (image_id is None):
            image_id = hashlib.md5(im.tobytes()).hexdigest()
        url = img2b64url(im)
        super().__init__(image_id, url)

class ImageFile(ImageObject):
    def __init__(self, fn: str, image_id=None):
        mime = None
        bn, ext = path.splitext(fn)
        if (ext.lower() in [".jpg", ".jpeg"]):
            mime = "image/jpeg"
        elif (ext.lower() in [".gif", ".png", ".bmp", ".webp"]):
            mime = "image/"+ext[1:]
        else:
            raise Exception('Unknown image type %s'%ext)
        if (image_id is None):
            image_id = hashlib.md5(f"{fn}-{path.getmtime(fn)}".encode("utf-8")).hexdigest()
        with open(fn, "rb") as f:
            data = f.read()
            b64 = base64.b64encode(data).decode("ascii")
        url = f"data:{mime};base64,{b64}"
        super().__init__(image_id, url)

