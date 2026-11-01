FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY . /app/
RUN python scripts/render_build.py \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin nehedrou
USER 10001:10001
EXPOSE 10000
CMD ["python", "scripts/render_start.py"]
