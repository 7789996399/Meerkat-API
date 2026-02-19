FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

# Install CPU-only torch first to avoid pulling the ~2GB CUDA version,
# then install the remaining dependencies.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

RUN python -m spacy download en_core_web_trf

COPY app/ app/

# Pre-download DeBERTa-large-MNLI at build time so startup is fast
RUN python -c "from transformers import pipeline; pipeline('text-classification', model='microsoft/deberta-large-mnli')"

EXPOSE 8002

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
