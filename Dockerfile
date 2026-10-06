FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/model-cache HF_HUB_DISABLE_TELEMETRY=1 HF_HUB_DISABLE_XET=1 OMP_NUM_THREADS=2 TOKENIZERS_PARALLELISM=false
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.8.0 && pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY static ./static
COPY tests ./tests
COPY LICENSE THIRD_PARTY_NOTICES.md ./
RUN mkdir -p /state /model-cache
EXPOSE 2983
CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "2983", "--no-access-log"]
