FROM python:3.12-slim

# opencv-python-headless + onnxruntime need only libgomp at runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend
COPY agents ./agents

# Download the OCR models at build time so the first request is fast and the container works offline.
RUN python -c "from rapidocr_onnxruntime import RapidOCR; RapidOCR()"

ENV RECEIPTIQ_DATA_DIR=/data
VOLUME ["/data"]
EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
