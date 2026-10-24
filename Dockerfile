FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MTWIN_CACHE_DIR=/tmp/mtwin-cache

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN useradd --create-home app && chown -R app /app
USER app

EXPOSE 8501
HEALTHCHECK CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8501/_stcore/health')"
CMD ["sh", "-c", "streamlit run streamlit_app.py --server.port=${PORT:-8501} --server.address=0.0.0.0"]
