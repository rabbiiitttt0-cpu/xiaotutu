# ===== 看图兔后端生产镜像（识图专用）=====
# Python 3.12：rapidocr 1.4.x 要求 <3.13
FROM python:3.12-slim

WORKDIR /app

# 系统依赖：fontconfig（CJK 字体）+ 编译工具 + curl
# 国内构建：Debian 源换阿里云镜像
# libgl1/libglib2.0-0/libxcb1/libsm6/libxext6/libxrender1：rapidocr 依赖的
# opencv-python（非 headless）运行时必需，slim 镜像缺失会导致 OCR 全链路静默失败
# （libxcb.so.1 / libgthread-2.0.so.0 报错，生产实测踩坑两轮）
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl fontconfig \
    libgl1 libglib2.0-0 libxcb1 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r /app/backend/requirements.txt

# 后端代码 + 双前端产物 + 字体 + LibreDWG
COPY backend /app/backend
COPY frontend-pc/dist /app/frontend-pc/dist
COPY frontend-mobile/dist /app/frontend-mobile/dist
COPY assets/fonts /app/assets/fonts
COPY assets/fonts /usr/share/fonts/truetype/appcjk
COPY assets/bin/libredwg/linux/dwg2dxf /app/assets/bin/libredwg/linux/dwg2dxf
COPY assets/bin/libredwg/linux/libredwg.so.0 /usr/local/lib/libredwg.so.0
RUN fc-cache -f && chmod +x /app/assets/bin/libredwg/linux/dwg2dxf && ldconfig

RUN mkdir -p /app/data /app/output

EXPOSE 7780

# 识图并发低，2 worker 足够（渲染/OCR 是 CPU 密集，4 worker 在 2C 上反而互相抢）
WORKDIR /app/backend
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7780", "--workers", "2"]
